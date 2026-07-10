from __future__ import annotations

import importlib.util
import hashlib
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable

import pyffish

from .schess_pgn import iter_uci_games


@dataclass(frozen=True)
class PositionRecord:
    ply: int
    move_number: int
    side: str
    fen: str
    variant: str
    site: str
    previous_move: str | None
    previous_uci: str | None


@dataclass(frozen=True)
class MoveEval:
    move: str
    san: str
    score_cp: int
    pv: list[str]


@dataclass(frozen=True)
class Selection:
    position: PositionRecord
    kind: str
    best: MoveEval
    second: MoveEval | None
    reason: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectionConfig:
    depth: int = 12
    multipv: int = 8
    win_cp: int = 200
    draw_floor_cp: int = -80
    losing_cp: int = -150
    min_gap_cp: int = 150
    max_plies: int = 7
    extension_beam_width: int = 1
    extend_critical: bool = False
    prefer_quiet_replies: bool = True
    eval_cache_dir: Path | None = None
    skip_standard_positions: bool = True
    confirm_depth: int | None = None
    confirm_multipv: int | None = None
    confirm_fast_depth: int | None = None
    confirm_clear_gap_cp: int = 300
    confirm_clear_margin_cp: int = 300
    confirm_borderline_depth: int | None = None
    confirm_borderline_win_cp: int | None = None
    confirm_borderline_gap_cp: int | None = None
    rescreen_depth: int | None = None
    rescreen_multipv: int | None = None
    rescreen_min_gap_cp: int = 80
    rescreen_margin_cp: int = 120
    profile_jsonl: Path | None = None
    eval_context: str = "root"


def positions_from_pgn(path: Path, configured_variant: str = "seirawan") -> list[PositionRecord]:
    records: list[PositionRecord] = []
    for game in iter_uci_games(path, configured_variant):
        variant = game.variant
        start_fen = game.start_fen
        site = game.headers.get("Site", "")
        stack: list[str] = []
        previous_move: str | None = None
        previous_uci: str | None = None
        records.append(_record(0, variant, start_fen, site, stack, previous_move, previous_uci))
        for uci in game.moves:
            stack.append(uci)
            previous_move = pyffish.get_san_moves(variant, start_fen, stack)[-1]
            previous_uci = uci
            records.append(_record(len(stack), variant, start_fen, site, stack, previous_move, previous_uci))
    return records


def select_tactics(
    positions: Iterable[PositionRecord],
    engine_path: Path,
    config: SelectionConfig,
    uci_module_path: Path,
) -> list[Selection]:
    engine = _load_uci_engine(uci_module_path, engine_path)
    selections: list[Selection] = []
    seen_motifs: set[tuple[str, str, str]] = set()
    skip_until_ply = -1
    current_site: str | None = None
    for position in positions:
        if position.site != current_site:
            current_site = position.site
            skip_until_ply = -1
        if position.ply <= skip_until_ply:
            continue
        if config.skip_standard_positions and not _has_schess_material(position.fen):
            continue
        legal_count = len(pyffish.legal_moves(position.variant, position.fen, []))
        if legal_count < 2:
            continue
        evals = evaluate_position(position, engine, config)
        selection = classify_position(position, evals, config)
        if selection is None and _needs_rescreen(position, evals, config):
            rescreen_config = _rescreen_config(config)
            selection = classify_position(position, evaluate_position(position, engine, rescreen_config), rescreen_config)
            if selection:
                selection = Selection(
                    selection.position,
                    selection.kind,
                    selection.best,
                    selection.second,
                    f"{selection.reason}; rescreened at depth {rescreen_config.depth}",
                    selection.flags,
                )
        if selection:
            selection = confirm_selection(selection, engine, config)
            if selection is None:
                continue
            if config.extend_critical:
                extension_config = replace(config, eval_context="extension")
                selection = extend_selection(selection, engine, extension_config)
            motif = (_canonical_fen(position.fen), selection.kind, selection.best.move)
            if motif in seen_motifs:
                continue
            seen_motifs.add(motif)
            selections.append(selection)
            skip_until_ply = max(skip_until_ply, position.ply + max(0, len(selection.best.pv) - 1))
    return selections


def evaluate_position(position: PositionRecord, engine, config: SelectionConfig) -> list[MoveEval]:
    started = time.perf_counter()
    legal_count = len(pyffish.legal_moves(position.variant, position.fen, []))
    cached = _read_eval_cache(position, config)
    if cached is not None:
        _profile_event(
            config,
            "engine_eval",
            position,
            started,
            legal_count=legal_count,
            cache_hit=True,
            result_count=len(cached),
        )
        return cached

    engine.setoption("UCI_Variant", position.variant)
    engine.setoption("multipv", min(config.multipv, legal_count))
    engine.newgame()
    engine.position(position.fen, [])
    _, info = engine.go(depth=config.depth)
    if not info:
        _profile_event(config, "engine_eval", position, started, legal_count=legal_count, cache_hit=False, result_count=0)
        return []

    evals: list[MoveEval] = []
    for item in info[-1]:
        move = item.get("pv", [""])[0]
        if not move:
            continue
        evals.append(
            MoveEval(
                move=move,
                san=pyffish.get_san_moves(position.variant, position.fen, [move])[-1],
                score_cp=_score_to_cp(item["score"]),
                pv=item.get("pv", []),
            )
        )
    _write_eval_cache(position, config, evals)
    _profile_event(config, "engine_eval", position, started, legal_count=legal_count, cache_hit=False, result_count=len(evals))
    return evals

def evaluate_fen(variant: str, fen: str, engine, config: SelectionConfig) -> list[MoveEval]:
    record = PositionRecord(
        ply=0,
        move_number=int(fen.split()[-1]),
        side=fen.split()[1],
        fen=fen,
        variant=variant,
        site="",
        previous_move=None,
        previous_uci=None,
    )
    return evaluate_position(record, engine, config)


def confirm_selection(selection: Selection, engine, config: SelectionConfig) -> Selection | None:
    if not config.confirm_depth or config.confirm_depth <= config.depth:
        return selection

    depths: list[tuple[int, bool]] = []
    if config.confirm_fast_depth and config.depth < config.confirm_fast_depth < config.confirm_depth:
        depths.append((config.confirm_fast_depth, True))
    depths.append((config.confirm_depth, False))

    last_evals: list[MoveEval] = []
    for depth, fast_pass in depths:
        confirm_config = _confirm_config(config, depth)
        last_evals = evaluate_position(selection.position, engine, confirm_config)
        confirmed = classify_position(selection.position, last_evals, confirm_config)
        if confirmed is None or confirmed.kind != selection.kind or confirmed.best.move != selection.best.move:
            if fast_pass:
                continue
            break
        if fast_pass:
            if _clear_confirmation(confirmed, confirm_config):
                return _confirmed_selection(selection, confirmed, f"confirmed at depth {depth} (clear)")
            continue
        if _needs_borderline_confirmation(confirmed, config):
            deeper = _borderline_confirmation(selection, engine, config, last_evals)
            if deeper is None:
                return None
            return _confirmed_selection(selection, deeper, f"confirmed at depth {config.confirm_borderline_depth} (borderline)")
        return _confirmed_selection(selection, confirmed, f"confirmed at depth {depth}")

    if config.confirm_borderline_depth and config.confirm_borderline_depth > config.confirm_depth:
        deeper = _borderline_confirmation(selection, engine, config, last_evals)
        if deeper is not None:
            return _confirmed_selection(selection, deeper, f"confirmed at depth {config.confirm_borderline_depth} (borderline)")
    return None


def _confirm_config(config: SelectionConfig, depth: int) -> SelectionConfig:
    return SelectionConfig(
        depth=depth,
        multipv=config.confirm_multipv or config.multipv,
        win_cp=config.win_cp,
        draw_floor_cp=config.draw_floor_cp,
        losing_cp=config.losing_cp,
        min_gap_cp=config.min_gap_cp,
        max_plies=config.max_plies,
        extension_beam_width=config.extension_beam_width,
        extend_critical=False,
        prefer_quiet_replies=config.prefer_quiet_replies,
        eval_cache_dir=config.eval_cache_dir,
        skip_standard_positions=config.skip_standard_positions,
        confirm_depth=None,
        confirm_multipv=None,
        confirm_fast_depth=None,
        confirm_clear_gap_cp=config.confirm_clear_gap_cp,
        confirm_clear_margin_cp=config.confirm_clear_margin_cp,
        confirm_borderline_depth=None,
        confirm_borderline_win_cp=config.confirm_borderline_win_cp,
        confirm_borderline_gap_cp=config.confirm_borderline_gap_cp,
        profile_jsonl=config.profile_jsonl,
        eval_context="confirm",
    )


def _borderline_config(config: SelectionConfig) -> SelectionConfig:
    depth = config.confirm_borderline_depth or config.confirm_depth or config.depth
    confirm_config = _confirm_config(config, depth)
    return replace(
        confirm_config,
        win_cp=config.confirm_borderline_win_cp or config.win_cp,
        min_gap_cp=config.confirm_borderline_gap_cp or config.min_gap_cp,
        eval_context="confirm_borderline",
    )


def _confirmed_selection(selection: Selection, confirmed: Selection, confirmation: str) -> Selection:
    return Selection(
        selection.position,
        confirmed.kind,
        confirmed.best,
        confirmed.second,
        f"{selection.reason}; {confirmation}",
        selection.flags,
    )


def _clear_confirmation(selection: Selection, config: SelectionConfig) -> bool:
    if selection.second is None:
        return True
    gap = selection.best.score_cp - selection.second.score_cp
    if gap < config.confirm_clear_gap_cp:
        return False
    margin = config.confirm_clear_margin_cp
    if selection.kind == "winning":
        return selection.best.score_cp >= config.win_cp + margin and selection.second.score_cp < config.win_cp
    if selection.kind == "drawing":
        return selection.best.score_cp >= config.draw_floor_cp and selection.second.score_cp <= config.losing_cp - margin
    return False


def _needs_borderline_confirmation(selection: Selection, config: SelectionConfig) -> bool:
    if not config.confirm_borderline_depth or config.confirm_borderline_depth <= (config.confirm_depth or 0):
        return False
    if selection.second is None:
        return False
    gap = selection.best.score_cp - selection.second.score_cp
    if selection.kind == "winning":
        return selection.best.score_cp < config.win_cp + config.confirm_clear_margin_cp or gap < config.confirm_clear_gap_cp
    if selection.kind == "drawing":
        return selection.best.score_cp < config.draw_floor_cp + config.confirm_clear_margin_cp or gap < config.confirm_clear_gap_cp
    return False


def _borderline_confirmation(
    selection: Selection,
    engine,
    config: SelectionConfig,
    previous_evals: list[MoveEval],
) -> Selection | None:
    relaxed_config = _borderline_config(config)
    if previous_evals:
        relaxed_previous = classify_position(selection.position, previous_evals, relaxed_config)
        if relaxed_previous is None or relaxed_previous.kind != selection.kind or relaxed_previous.best.move != selection.best.move:
            return None
    confirmed = classify_position(selection.position, evaluate_position(selection.position, engine, relaxed_config), relaxed_config)
    if confirmed is None or confirmed.kind != selection.kind or confirmed.best.move != selection.best.move:
        return None
    return confirmed

def extend_selection(selection: Selection, engine, config: SelectionConfig) -> Selection:
    beam_width = max(1, config.extension_beam_width)
    max_plies = config.max_plies
    if selection.kind == "drawing":
        max_plies = min(max_plies, 3)
    initial_line = [selection.best.move]
    if len(initial_line) >= max_plies:
        return selection

    variant = selection.position.variant
    initial_fen = pyffish.get_fen(variant, selection.position.fen, initial_line)
    beam: list[tuple[list[str], str, int, int]] = [(initial_line, initial_fen, 0, selection.best.score_cp)]
    best_line = initial_line
    best_rank = _extension_rank(best_line, 0, selection.best.score_cp)

    while True:
        next_beam: list[tuple[list[str], str, int, int]] = []
        for line, current_fen, check_penalty_sum, score_sum in beam:
            if len(line) + 2 > max_plies:
                continue
            for check_penalty, opponent_move, solver_move in find_forcing_replies(variant, current_fen, selection.kind, engine, config, beam_width):
                new_line = [*line, opponent_move, solver_move.move]
                new_fen = pyffish.get_fen(variant, current_fen, [opponent_move, solver_move.move])
                next_beam.append(
                    (
                        new_line,
                        new_fen,
                        check_penalty_sum + check_penalty,
                        score_sum + solver_move.score_cp,
                    )
                )

        if not next_beam:
            break

        next_beam.sort(key=lambda item: _extension_rank(item[0], item[2], item[3]))
        beam = next_beam[:beam_width]
        current_rank = _extension_rank(beam[0][0], beam[0][2], beam[0][3])
        if current_rank < best_rank:
            best_line = beam[0][0]
            best_rank = current_rank

    if best_line == selection.best.pv:
        return selection
    return Selection(
        selection.position,
        selection.kind,
        MoveEval(selection.best.move, selection.best.san, selection.best.score_cp, best_line),
        selection.second,
        selection.reason,
        selection.flags,
    )


def _extension_rank(line: list[str], check_penalty_sum: int, score_sum: int) -> tuple[int, int, int]:
    return (-len(line), check_penalty_sum, -score_sum)


def find_forcing_reply(
    variant: str,
    fen: str,
    kind: str,
    engine,
    config: SelectionConfig,
) -> tuple[str, MoveEval] | None:
    replies = find_forcing_replies(variant, fen, kind, engine, config, 1)
    if not replies:
        return None
    _, reply, solver_move = replies[0]
    return reply, solver_move


def find_forcing_replies(
    variant: str,
    fen: str,
    kind: str,
    engine,
    config: SelectionConfig,
    limit: int | None = None,
) -> list[tuple[int, str, MoveEval]]:
    started = time.perf_counter()
    legal_replies = pyffish.legal_moves(variant, fen, [])
    candidates: list[tuple[int, int, str, MoveEval]] = []
    evaluated_replies = 0
    skipped_standard = 0
    for reply in legal_replies:
        child_fen = pyffish.get_fen(variant, fen, [reply])
        if config.skip_standard_positions and not _has_schess_material(child_fen):
            skipped_standard += 1
            continue
        child_position = PositionRecord(
            ply=0,
            move_number=int(child_fen.split()[-1]),
            side=child_fen.split()[1],
            fen=child_fen,
            variant=variant,
            site="",
            previous_move=pyffish.get_san_moves(variant, fen, [reply])[-1],
            previous_uci=reply,
        )
        evaluated_replies += 1
        child_evals = evaluate_position(child_position, engine, config)
        child_selection = classify_position(child_position, child_evals, config)
        if child_selection and child_selection.kind == kind:
            gives_check = int(pyffish.gives_check(variant, fen, [reply]))
            check_penalty = gives_check if config.prefer_quiet_replies else 0
            candidates.append((check_penalty, child_selection.best.score_cp, reply, child_selection.best))

    _profile_event(
        config,
        "extension_reply_scan",
        None,
        started,
        fen=fen,
        legal_count=len(legal_replies),
        evaluated_replies=evaluated_replies,
        skipped_standard=skipped_standard,
        candidate_replies=len(candidates),
        beam_limit=limit or 0,
    )

    if not candidates:
        return []

    candidates.sort(key=lambda item: (item[0], -item[1]))
    selected = candidates[: max(1, limit or len(candidates))]
    return [(check_penalty, reply, solver_move) for check_penalty, _, reply, solver_move in selected]


def _rescreen_config(config: SelectionConfig) -> SelectionConfig:
    return replace(
        config,
        depth=config.rescreen_depth or config.depth,
        multipv=config.rescreen_multipv or config.multipv,
        rescreen_depth=None,
        rescreen_multipv=None,
        eval_context="rescreen",
    )


def _needs_rescreen(position: PositionRecord, evals: list[MoveEval], config: SelectionConfig) -> bool:
    if not config.rescreen_depth or config.rescreen_depth <= config.depth:
        return False
    if len(evals) < 2:
        return False
    best = evals[0]
    second = evals[1]
    gap = best.score_cp - second.score_cp
    if gap < config.rescreen_min_gap_cp:
        return False

    margin = config.rescreen_margin_cp
    near_winning = best.score_cp >= config.win_cp - margin and second.score_cp < config.win_cp + margin
    near_drawing = best.score_cp >= config.draw_floor_cp - margin and second.score_cp <= config.losing_cp + margin
    forcing = "+" in best.san or "#" in best.san or _is_capture_san(best.san)
    if near_winning or near_drawing:
        return True
    if forcing and best.score_cp >= config.draw_floor_cp - margin and second.score_cp <= config.win_cp + margin:
        return True
    return False


def _is_capture_san(san: str) -> bool:
    return "x" in san
def classify_position(
    position: PositionRecord,
    evals: list[MoveEval],
    config: SelectionConfig,
) -> Selection | None:
    if len(evals) < 2:
        return None

    best = evals[0]
    second = evals[1]
    puzzle_best = MoveEval(best.move, best.san, best.score_cp, [best.move])
    gap = best.score_cp - second.score_cp
    if gap < config.min_gap_cp:
        return None

    if best.score_cp >= config.win_cp and second.score_cp < config.win_cp:
        return Selection(
            position,
            "winning",
            puzzle_best,
            second,
            "only move keeps the side to move in winning territory",
            _flags(position, best),
        )

    if best.score_cp >= config.draw_floor_cp and second.score_cp <= config.losing_cp:
        return Selection(
            position,
            "drawing",
            puzzle_best,
            second,
            "only move escapes the losing range",
            _flags(position, best),
        )

    return None


def _record(
    ply: int,
    variant: str,
    start_fen: str,
    site: str,
    stack: list[str],
    previous_move: str | None,
    previous_uci: str | None,
) -> PositionRecord:
    fen = pyffish.get_fen(variant, start_fen, stack)
    side = fen.split()[1]
    move_number = int(fen.split()[-1])
    return PositionRecord(ply, move_number, side, fen, variant, site, previous_move, previous_uci)


def _flags(position: PositionRecord, best: MoveEval) -> tuple[str, ...]:
    flags: list[str] = []
    if position.previous_uci and _destination(best.move) == _destination(position.previous_uci):
        flags.append("recapture")
    if len(best.pv) <= 1:
        flags.append("one-move")
    return tuple(flags)


def _destination(move: str) -> str:
    return move[2:4]


def _canonical_fen(fen: str) -> str:
    fields = fen.split()
    return " ".join(fields[:4])


def _has_schess_material(fen: str) -> bool:
    board_and_pockets = fen.split()[0]
    if any(piece in board_and_pockets for piece in "HEhe"):
        return True
    board = board_and_pockets.split("[", 1)[0]
    ranks = board.split("/")
    if len(ranks) != 8:
        return False
    return "P" in ranks[1] or "p" in ranks[6]


def _score_to_cp(score: list[str]) -> int:
    kind, value = score[0], int(score[1])
    if kind == "cp":
        return value
    if value > 0:
        return 100000 - value
    return -100000 - value



def _profile_event(config: SelectionConfig, event: str, position: PositionRecord | None, started: float, **extra) -> None:
    if config.profile_jsonl is None:
        return
    payload = {
        "event": event,
        "context": config.eval_context,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "depth": config.depth,
        "multipv": config.multipv,
        **extra,
    }
    if position is not None:
        payload.update(
            {
                "fen": position.fen,
                "move_number": position.move_number,
                "side": position.side,
                "ply": position.ply,
                "source": position.site,
            }
        )
    config.profile_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with config.profile_jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

def _read_eval_cache(position: PositionRecord, config: SelectionConfig) -> list[MoveEval] | None:
    path = _eval_cache_path(position, config)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    try:
        return [MoveEval(**item) for item in data.get("evals", [])]
    except TypeError:
        return None


def _write_eval_cache(position: PositionRecord, config: SelectionConfig, evals: list[MoveEval]) -> None:
    path = _eval_cache_path(position, config)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cache_version": 1,
        "variant": position.variant,
        "fen": position.fen,
        "depth": config.depth,
        "multipv": config.multipv,
        "evals": [asdict(item) for item in evals],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _eval_cache_path(position: PositionRecord, config: SelectionConfig) -> Path | None:
    if config.eval_cache_dir is None:
        return None
    key_data = {
        "cache_version": 1,
        "variant": position.variant,
        "fen": position.fen,
        "depth": config.depth,
        "multipv": config.multipv,
    }
    key = hashlib.sha256(json.dumps(key_data, sort_keys=True).encode("utf-8")).hexdigest()
    return config.eval_cache_dir / f"{key}.json"


def _normalize_variant(value: str) -> str:
    normalized = value.lower().replace("-", "").replace("_", "")
    if "seirawan" in normalized or normalized == "schess":
        return "seirawan"
    return value.lower()


def _load_uci_engine(uci_module_path: Path, engine_path: Path):
    spec = importlib.util.spec_from_file_location("variant_puzzler_uci", uci_module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load UCI module from {uci_module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Engine([str(engine_path)])
