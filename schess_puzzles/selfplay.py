from __future__ import annotations

import importlib.util
import math
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pyffish


@dataclass(frozen=True)
class SelfPlayConfig:
    games: int = 10
    variant: str = "seirawan"
    depth: int = 2
    skill_level: int | None = None
    uci_limit_strength: bool = False
    uci_elo: int | None = None
    multipv: int = 6
    max_plies: int = 160
    temperature_cp: int = 180
    blunder_chance: float = 0.15
    resign_cp: int = 700
    resign_moves: int = 5
    seed: int | None = None
    event: str = "S-Chess Fairy-Stockfish self-play"
    prefix: str = "selfplay"


def generate_selfplay_pgns(
    *,
    engine_path: Path,
    uci_module_path: Path,
    output_dir: Path,
    config: SelfPlayConfig,
) -> list[Path]:
    rng = random.Random(config.seed)
    engine = _load_uci_engine(uci_module_path, engine_path)
    engine.setoption("UCI_Variant", config.variant)
    _configure_strength(engine, config)
    engine.setoption("multipv", config.multipv)

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for game_index in range(1, config.games + 1):
        game = _play_one_game(engine, rng, config, game_index)
        path = output_dir / f"{config.prefix}_{game_index:04d}.pgn"
        path.write_text(game, encoding="utf-8")
        paths.append(path)
    return paths


def _play_one_game(engine, rng: random.Random, config: SelfPlayConfig, game_index: int) -> str:
    start_fen = pyffish.start_fen(config.variant)
    moves: list[str] = []
    engine.newgame()

    result = "*"
    termination = "Max plies reached"
    losing_turns = {"w": 0, "b": 0}
    for _ply in range(config.max_plies):
        legal_moves = pyffish.legal_moves(config.variant, start_fen, moves)
        if not legal_moves:
            result, termination = _terminal_result(config.variant, start_fen, moves)
            break
        move, score_cp = _choose_move(engine, rng, config, start_fen, moves, legal_moves)
        side = pyffish.get_fen(config.variant, start_fen, moves).split()[1]
        if _should_resign(side, score_cp, losing_turns, config):
            result = "0-1" if side == "w" else "1-0"
            termination = f"{'White' if side == 'w' else 'Black'} resigned"
            break
        moves.append(move)

    sans = pyffish.get_san_moves(config.variant, start_fen, moves)
    headers = {
        "Event": config.event,
        "Site": "local-selfplay",
        "Date": datetime.now().strftime("%Y.%m.%d"),
        "Round": str(game_index),
        "White": f"FairyStockfish-low-{config.depth}",
        "Black": f"FairyStockfish-low-{config.depth}",
        "Result": result,
        "Variant": "Seirawan",
        "Termination": termination,
        "EngineDepth": str(config.depth),
        "EngineSkillLevel": "" if config.skill_level is None else str(config.skill_level),
        "EngineLimitStrength": str(config.uci_limit_strength),
        "EngineUciElo": "" if config.uci_elo is None else str(config.uci_elo),
        "EngineMultiPV": str(config.multipv),
        "BlunderChance": f"{config.blunder_chance:.3f}",
        "TemperatureCp": str(config.temperature_cp),
        "ResignCp": str(config.resign_cp),
        "ResignMoves": str(config.resign_moves),
    }
    return _format_pgn(headers, sans, result)


def _choose_move(
    engine,
    rng: random.Random,
    config: SelfPlayConfig,
    start_fen: str,
    moves: list[str],
    legal_moves: list[str],
) -> tuple[str, int | None]:
    if rng.random() < config.blunder_chance:
        return rng.choice(legal_moves), None

    fen = pyffish.get_fen(config.variant, start_fen, moves)
    engine.setoption("UCI_Variant", config.variant)
    _configure_strength(engine, config)
    engine.setoption("multipv", min(config.multipv, len(legal_moves)))
    engine.position(fen, [])
    bestmove, info = engine.go(depth=config.depth)
    candidates = _engine_candidates(info, legal_moves)
    if not candidates:
        return bestmove if bestmove in legal_moves else rng.choice(legal_moves), None
    return _weighted_choice(candidates, rng, config.temperature_cp), max(score for _move, score in candidates)


def _should_resign(
    side: str,
    score_cp: int | None,
    losing_turns: dict[str, int],
    config: SelfPlayConfig,
) -> bool:
    if config.resign_moves <= 0 or score_cp is None:
        return False
    if score_cp <= -abs(config.resign_cp):
        losing_turns[side] += 1
        return losing_turns[side] >= config.resign_moves
    losing_turns[side] = 0
    return False


def _engine_candidates(info, legal_moves: list[str]) -> list[tuple[str, int]]:
    if not info:
        return []
    legal = set(legal_moves)
    candidates: list[tuple[str, int]] = []
    for item in info[-1]:
        pv = item.get("pv", [])
        if not pv or pv[0] not in legal:
            continue
        score = _score_to_cp(item.get("score", ["cp", "0"]))
        candidates.append((pv[0], score))
    return candidates


def _weighted_choice(candidates: list[tuple[str, int]], rng: random.Random, temperature_cp: int) -> str:
    if temperature_cp <= 0:
        return max(candidates, key=lambda item: item[1])[0]
    best = max(score for _move, score in candidates)
    weights = [math.exp((score - best) / temperature_cp) for _move, score in candidates]
    return rng.choices([move for move, _score in candidates], weights=weights, k=1)[0]


def _configure_strength(engine, config: SelfPlayConfig) -> None:
    if config.skill_level is not None:
        engine.setoption("Skill Level", config.skill_level)
    if config.uci_limit_strength:
        engine.setoption("UCI_LimitStrength", "true")
    if config.uci_elo is not None:
        engine.setoption("UCI_Elo", config.uci_elo)


def _score_to_cp(score: list[str]) -> int:
    kind = score[0]
    value = int(score[1])
    if kind == "cp":
        return value
    if value > 0:
        return 100000 - value
    return -100000 - value


def _terminal_result(variant: str, start_fen: str, moves: list[str]) -> tuple[str, str]:
    fen = pyffish.get_fen(variant, start_fen, moves)
    side = fen.split()[1]
    in_check = bool(moves and pyffish.gives_check(variant, start_fen, moves))
    if not in_check:
        return "1/2-1/2", "Stalemate"
    return ("0-1", "Checkmate") if side == "w" else ("1-0", "Checkmate")


def _format_pgn(headers: dict[str, str], sans: list[str], result: str) -> str:
    lines = [f'[{key} "{value}"]' for key, value in headers.items()]
    lines.append("")
    move_parts: list[str] = []
    for index in range(0, len(sans), 2):
        move_number = index // 2 + 1
        if index + 1 < len(sans):
            move_parts.append(f"{move_number}. {sans[index]} {sans[index + 1]}")
        else:
            move_parts.append(f"{move_number}. {sans[index]}")
    move_parts.append(result)
    lines.append(" ".join(move_parts))
    lines.append("")
    return "\n".join(lines)


def _load_uci_engine(uci_module_path: Path, engine_path: Path):
    spec = importlib.util.spec_from_file_location("variant_puzzler_uci", uci_module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load UCI module from {uci_module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Engine([str(engine_path)])
