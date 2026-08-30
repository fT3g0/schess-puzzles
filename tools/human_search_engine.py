"""Prototype of a selective, human-oriented chess search.

This is not a strength engine. It uses legal moves only from pyffish and makes every
search choice explicit: forcing/simplifying candidate ordering, a shallow positional
evaluation, and conversion certificates that end lines once a human would normally
stop calculating.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forcingness_analysis import VALUES, attack_map, board_from_fen, move_features


MAX_CANDIDATES = 5
SEARCH_DEPTH = 4
CONFIDENCE_MARGIN = 250


@dataclass
class SearchResult:
    score: int
    nodes: int
    cutoff: str
    best_move: str
    candidate_count: int
    confidence_stops: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=Path("data/complexity/lichess_transition_probe_500.json"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--depth", type=int, default=SEARCH_DEPTH)
    parser.add_argument("--candidates", type=int, default=MAX_CANDIDATES)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/complexity/lichess_human_search_probe.json"),
    )
    return parser.parse_args()


def deterministic_subset(profiles: list[dict], limit: int) -> list[dict]:
    if not limit or limit >= len(profiles):
        return profiles
    return sorted(profiles, key=lambda item: hashlib.sha1(item["PuzzleId"].encode()).hexdigest())[:limit]


def material_balance(fen: str, perspective_white: bool) -> int:
    total = 0
    for piece in board_from_fen(fen).values():
        if piece.upper() == "K":
            continue
        value = VALUES.get(piece.upper(), 0) * 100
        total += value if piece.isupper() == perspective_white else -value
    return total


def in_check(fen: str, white: bool) -> bool:
    board = board_from_fen(fen)
    king = next((square for square, piece in board.items() if piece == ("K" if white else "k")), "")
    return bool(king and king in attack_map(board, not white))


def forcing_count(fen: str, white: bool) -> int:
    board = board_from_fen(fen)
    return sum(
        move_features(fen, board, move, white)["level"] >= 2
        for move in pyffish.legal_moves("chess", fen, [])
    )


def hanging_material(fen: str, owner_white: bool) -> int:
    """Largest readily available target for the opponent, in centipawns."""
    board = board_from_fen(fen)
    attacks = attack_map(board, not owner_white)
    defenders = attack_map(board, owner_white)
    gains = []
    for square, piece in board.items():
        if piece.isupper() != owner_white or piece.upper() == "K" or square not in attacks:
            continue
        victim = VALUES.get(piece.upper(), 0) * 100
        cheapest = min(VALUES.get(board[source].upper(), 0) * 100 for source in attacks[square])
        gains.append(victim if square not in defenders else max(0, victim - cheapest))
    return max(gains, default=0)


def static_score(fen: str, perspective_white: bool) -> int:
    """Small positional vocabulary intended for explainability, not playing strength."""
    score = material_balance(fen, perspective_white)
    own_hanging = hanging_material(fen, perspective_white)
    opponent_hanging = hanging_material(fen, not perspective_white)
    score += opponent_hanging - own_hanging
    if in_check(fen, perspective_white):
        score -= 120
    if in_check(fen, not perspective_white):
        score += 120
    return score


def conversion_certificate(fen: str, perspective_white: bool) -> tuple[bool, str]:
    """Return a conservative human stopping condition.

    A material edge alone is insufficient. The trailing side must also have little
    forcing counterplay and the leading side must not currently be in check.
    """
    material = material_balance(fen, perspective_white)
    ahead_white = material > 0
    leader_white = perspective_white if ahead_white else not perspective_white
    leader_margin = abs(material)
    if leader_margin < 300:
        return False, ""
    if in_check(fen, leader_white):
        return False, ""
    trailing_forcing = forcing_count(fen, not leader_white)
    trailing_hanging = hanging_material(fen, leader_white)
    if leader_margin >= 500 and trailing_forcing <= 2 and trailing_hanging < 300:
        return True, "clear_major_material"
    if leader_margin >= 300 and trailing_forcing == 0 and trailing_hanging == 0:
        return True, "quiet_material_conversion"
    return False, ""


@lru_cache(maxsize=100000)
def candidate_records(fen: str, maximum: int) -> tuple[tuple[str, int, int, int], ...]:
    board = board_from_fen(fen)
    white = fen.split()[1] == "w"
    legal = pyffish.legal_moves("chess", fen, [])
    parent_mobility = len(legal)
    # First pass is cheap and supplies the human forcing hierarchy.
    basic = []
    for move in legal:
        feature = move_features(fen, board, move, white)
        priority = feature["level"] * 1000 + feature["captured_value"] * 80 + feature["material_threat_value"] * 60
        basic.append((move, priority, feature["level"]))
    basic.sort(key=lambda item: (-item[1], item[0]))
    # Only inspect simplification for an already plausible shortlist. This is both
    # a computational bound and a model of selective human attention.
    shortlisted = basic[:max(8, maximum * 2)]
    enriched = []
    for move, priority, level in shortlisted:
        child = pyffish.get_fen("chess", fen, [move])
        simplification = max(0, parent_mobility - len(pyffish.legal_moves("chess", child, [])))
        enriched.append((move, priority + min(300, simplification * 12), level, simplification))
    enriched.sort(key=lambda item: (-item[1], item[0]))
    forcing = [item for item in enriched if item[2] >= 1]
    selected = forcing[:maximum]
    if len(selected) < maximum:
        used = {item[0] for item in selected}
        selected.extend(item for item in enriched if item[0] not in used)
        selected = selected[:maximum]
    return tuple(selected)


def terminal_score(fen: str, perspective_white: bool) -> int | None:
    legal = pyffish.legal_moves("chess", fen, [])
    if legal:
        return None
    side_white = fen.split()[1] == "w"
    if in_check(fen, side_white):
        return -100_000 if side_white == perspective_white else 100_000
    return 0


def search(fen: str, perspective_white: bool, depth: int, maximum: int) -> SearchResult:
    terminal = terminal_score(fen, perspective_white)
    if terminal is not None:
        return SearchResult(terminal, 1, "terminal", "", 0, 0)
    converted, reason = conversion_certificate(fen, perspective_white)
    if converted:
        return SearchResult(static_score(fen, perspective_white), 1, reason, "", 0, 0)
    if depth <= 0:
        return SearchResult(static_score(fen, perspective_white), 1, "horizon", "", 0, 0)

    side_white = fen.split()[1] == "w"
    records = candidate_records(fen, maximum)
    children: list[tuple[str, SearchResult]] = []
    for move, _, forcing_level, _ in records:
        child = pyffish.get_fen("chess", fen, [move])
        children.append((move, search(child, perspective_white, depth - 1, maximum)))

    maximizing = side_white == perspective_white
    ordered = sorted(children, key=lambda pair: pair[1].score, reverse=maximizing)
    best_record, best_result = ordered[0]
    second_score = ordered[1][1].score if len(ordered) > 1 else None
    confidence = (
        second_score is not None
        and ((best_result.score - second_score) if maximizing else (second_score - best_result.score)) >= CONFIDENCE_MARGIN
    )
    return SearchResult(
        best_result.score,
        1 + sum(result.nodes for _, result in children),
        "confidence_gap" if confidence else "searched",
        best_record,
        len(records),
        sum(result.confidence_stops for _, result in children) + int(confidence),
    )


def profile_puzzle(profile: dict, depth: int, maximum: int) -> dict:
    moves = profile["Moves"].split()
    decisions = []
    for node in profile["nodes"]:
        ply = int(node["ply"])
        fen = pyffish.get_fen("chess", profile["InitialFEN"], moves[:ply])
        solver_white = fen.split()[1] == "w"
        result = search(fen, solver_white, depth, maximum)
        decisions.append({
            "ply": ply,
            "solution_uci": node["solution_uci"],
            "selected_uci": result.best_move,
            "solution_selected": result.best_move == node["solution_uci"],
            "nodes": result.nodes,
            "candidate_count": result.candidate_count,
            "cutoff": result.cutoff,
            "confidence_stops": result.confidence_stops,
        })
    metrics = {
        "human_search_nodes": sum(item["nodes"] for item in decisions),
        "human_mean_candidates": round(sum(item["candidate_count"] for item in decisions) / len(decisions), 3),
        "human_solution_match_rate": round(sum(item["solution_selected"] for item in decisions) / len(decisions), 3),
        "human_confidence_stops": sum(item["confidence_stops"] for item in decisions),
        "human_conversion_stops": sum(item["cutoff"] in {"clear_major_material", "quiet_material_conversion"} for item in decisions),
    }
    profile["human_search"] = {"decisions": decisions, "metrics": metrics}
    profile["metrics"].update(metrics)
    return profile


def spearman(values: list[float], ratings: list[float]) -> float:
    def ranks(items: list[float]) -> list[float]:
        order = sorted(range(len(items)), key=lambda index: items[index])
        result = [0.0] * len(items)
        for rank, index in enumerate(order, start=1):
            result[index] = rank
        return result
    left, right = ranks(values), ranks(ratings)
    left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - left_mean) ** 2 for a in left) * sum((b - right_mean) ** 2 for b in right))
    return round(numerator / denominator, 3) if denominator else 0.0


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = deterministic_subset(report["profiles"], args.limit)
    completed = []
    for index, profile in enumerate(profiles, start=1):
        try:
            completed.append(profile_puzzle(profile, args.depth, args.candidates))
            metrics = completed[-1]["metrics"]
            print(f"[{index}/{len(profiles)}] {profile['PuzzleId']}: rating={profile['Rating']} nodes={metrics['human_search_nodes']} match={metrics['human_solution_match_rate']}")
        except Exception as exc:
            print(f"skip {profile['PuzzleId']}: {exc}")
    report["profiles"] = completed
    metrics = ["human_search_nodes", "human_mean_candidates", "human_solution_match_rate", "human_confidence_stops", "human_conversion_stops"]
    ratings = [float(profile["Rating"]) for profile in completed]
    report["human_search_definition"] = {
        "candidate_order": "forcing moves (check/capture/threat) first, then captured value, material threat, and reduction in opponent legal moves",
        "evaluation": "material excluding kings plus hanging-material and check terms; no external engine evaluation",
        "certificates": "stop at terminal positions or sufficiently large, quiet material edges with little forcing counterplay",
        "search": f"depth={args.depth}, at most {args.candidates} candidates per position",
    }
    report["human_search_correlations"] = {
        metric: spearman([float(profile["metrics"][metric]) for profile in completed], ratings)
        for metric in metrics
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Human-search Spearman correlations:", report["human_search_correlations"])
    print(f"Wrote {args.output} for {len(completed)} puzzle(s).")


if __name__ == "__main__":
    main()
