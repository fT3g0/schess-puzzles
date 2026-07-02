from __future__ import annotations

import importlib.util
import hashlib
import json
from dataclasses import asdict, dataclass
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
    extend_critical: bool = False
    prefer_quiet_replies: bool = True
    eval_cache_dir: Path | None = None
    skip_standard_positions: bool = True
    confirm_depth: int | None = None
    confirm_multipv: int | None = None


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
    for position in positions:
        if position.ply <= skip_until_ply:
            continue
        if config.skip_standard_positions and not _has_schess_material(position.fen):
            continue
        legal_count = len(pyffish.legal_moves(position.variant, position.fen, []))
        if legal_count < 2:
            continue
        evals = evaluate_position(position, engine, config)
        selection = classify_position(position, evals, config)
        if selection:
            selection = confirm_selection(selection, engine, config)
            if selection is None:
                continue
            if config.extend_critical:
                selection = extend_selection(selection, engine, config)
            motif = (_canonical_fen(position.fen), selection.kind, selection.best.move)
            if motif in seen_motifs:
                continue
            seen_motifs.add(motif)
            selections.append(selection)
            skip_until_ply = max(skip_until_ply, position.ply + max(0, len(selection.best.pv) - 1))
    return selections


def evaluate_position(position: PositionRecord, engine, config: SelectionConfig) -> list[MoveEval]:
    cached = _read_eval_cache(position, config)
    if cached is not None:
        return cached

    engine.setoption("UCI_Variant", position.variant)
    engine.setoption("multipv", min(config.multipv, len(pyffish.legal_moves(position.variant, position.fen, []))))
    engine.newgame()
    engine.position(position.fen, [])
    _, info = engine.go(depth=config.depth)
    if not info:
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

    confirm_config = SelectionConfig(
        depth=config.confirm_depth,
        multipv=config.confirm_multipv or config.multipv,
        win_cp=config.win_cp,
        draw_floor_cp=config.draw_floor_cp,
        losing_cp=config.losing_cp,
        min_gap_cp=config.min_gap_cp,
        max_plies=config.max_plies,
        extend_critical=False,
        prefer_quiet_replies=config.prefer_quiet_replies,
        eval_cache_dir=config.eval_cache_dir,
        skip_standard_positions=config.skip_standard_positions,
        confirm_depth=None,
        confirm_multipv=None,
    )
    confirmed = classify_position(selection.position, evaluate_position(selection.position, engine, confirm_config), confirm_config)
    if confirmed is None or confirmed.kind != selection.kind or confirmed.best.move != selection.best.move:
        return None
    return Selection(
        selection.position,
        confirmed.kind,
        confirmed.best,
        confirmed.second,
        f"{selection.reason}; confirmed at depth {config.confirm_depth}",
        selection.flags,
    )


def extend_selection(selection: Selection, engine, config: SelectionConfig) -> Selection:
    line = [selection.best.move]
    if len(line) >= config.max_plies:
        return selection

    variant = selection.position.variant
    current_fen = pyffish.get_fen(variant, selection.position.fen, [selection.best.move])
    while len(line) + 2 <= config.max_plies:
        reply = find_forcing_reply(variant, current_fen, selection.kind, engine, config)
        if reply is None:
            break

        opponent_move, solver_move = reply
        line.extend([opponent_move, solver_move.move])
        current_fen = pyffish.get_fen(variant, current_fen, [opponent_move, solver_move.move])

    if line == selection.best.pv:
        return selection
    return Selection(
        selection.position,
        selection.kind,
        MoveEval(selection.best.move, selection.best.san, selection.best.score_cp, line),
        selection.second,
        selection.reason,
        selection.flags,
    )


def find_forcing_reply(
    variant: str,
    fen: str,
    kind: str,
    engine,
    config: SelectionConfig,
) -> tuple[str, MoveEval] | None:
    candidates: list[tuple[int, int, str, MoveEval]] = []
    for reply in pyffish.legal_moves(variant, fen, []):
        child_fen = pyffish.get_fen(variant, fen, [reply])
        if config.skip_standard_positions and not _has_schess_material(child_fen):
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
        child_evals = evaluate_position(child_position, engine, config)
        child_selection = classify_position(child_position, child_evals, config)
        if child_selection and child_selection.kind == kind:
            gives_check = int(pyffish.gives_check(variant, fen, [reply]))
            check_penalty = gives_check if config.prefer_quiet_replies else 0
            candidates.append((check_penalty, child_selection.best.score_cp, reply, child_selection.best))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    _, _, reply, solver_move = candidates[0]
    return reply, solver_move


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
    return any(piece in board_and_pockets for piece in "HEhe")


def _score_to_cp(score: list[str]) -> int:
    kind, value = score[0], int(score[1])
    if kind == "cp":
        return value
    if value > 0:
        return 100000 - value
    return -100000 - value


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
