"""Measure bounded static forcing trees for known Lichess solution decisions.

This is an execution-difficulty probe, not a replacement for engine search: it counts
how much forcing variation a player can reasonably need to organize around a solution.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forcingness_analysis import attack_map, board_from_fen, move_features


MAX_CHILDREN = 10
MAX_TREE_NODES = 32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_threat_width_500.json"))
    parser.add_argument("--plies", type=int, default=2, help="Further plies after the supplied solution move.")
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_move_difficulty_tree_500.json"))
    return parser.parse_args()


def side_in_check(fen: str) -> bool:
    board = board_from_fen(fen)
    white = fen.split()[1] == "w"
    king = next((square for square, piece in board.items() if piece == ("K" if white else "k")), "")
    return bool(king and king in attack_map(board, not white))


def forcing_children(fen: str) -> list[str]:
    board = board_from_fen(fen)
    white = fen.split()[1] == "w"
    legal = pyffish.legal_moves("chess", fen, [])
    if side_in_check(fen):
        return legal[:MAX_CHILDREN]
    featured = [(move_features(fen, board, move, white), move) for move in legal]
    forcing = [(feature, move) for feature, move in featured if feature["level"] >= 2]
    forcing.sort(key=lambda item: (-item[0]["level"], -item[0]["material_threat_value"], item[1]))
    return [move for _, move in forcing[:MAX_CHILDREN]]


def tree_metrics(root_fen: str, plies: int) -> dict[str, float | int]:
    nodes = 0
    leaves = 0
    decision_bits = 0.0
    max_depth = 0
    stack = [(root_fen, 0)]
    capped = False
    while stack:
        if nodes >= MAX_TREE_NODES:
            capped = True
            break
        fen, depth = stack.pop()
        nodes += 1
        max_depth = max(max_depth, depth)
        if depth >= plies:
            leaves += 1
            continue
        children = forcing_children(fen)
        if not children:
            leaves += 1
            continue
        decision_bits += math.log2(len(children))
        for move in children:
            stack.append((pyffish.get_fen("chess", fen, [move]), depth + 1))
    return {
        "tree_nodes": nodes,
        "tree_leaves": leaves,
        "tree_horizon": max_depth,
        "tree_decision_bits": round(decision_bits, 3),
        "tree_capped": capped,
    }


def enrich(profile: dict, plies: int) -> dict:
    moves = profile["Moves"].split()
    node_metrics = []
    for node in profile["nodes"]:
        root_fen = pyffish.get_fen("chess", profile["InitialFEN"], moves[: int(node["ply"]) + 1])
        tree = tree_metrics(root_fen, plies)
        node["forcing_tree"] = tree
        node_metrics.append(tree)
    mean = lambda key: round(sum(item[key] for item in node_metrics) / len(node_metrics), 3)
    profile["metrics"].update({
        "mean_forcing_tree_nodes": mean("tree_nodes"),
        "mean_forcing_tree_leaves": mean("tree_leaves"),
        "mean_forcing_tree_horizon": mean("tree_horizon"),
        "mean_forcing_tree_decision_bits": mean("tree_decision_bits"),
    })
    return profile


def main() -> None:
    args = parse_args()
    if args.plies < 1:
        raise SystemExit("--plies must be positive")
    report = json.loads(args.input.read_text(encoding="utf-8"))
    report["profiles"] = [enrich(profile, args.plies) for profile in report["profiles"]]
    report["forcing_tree_definition"] = {
        "plies_after_solution": args.plies,
        "children": "all legal replies while in check; otherwise checks, captures, and check-captures only",
        "max_children_per_node": MAX_CHILDREN, "max_nodes_per_tree": MAX_TREE_NODES,
        "scope": "static forcing-tree approximation for move-execution difficulty",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(report['profiles'])} puzzle(s), forcing tree depth={args.plies}.")


if __name__ == "__main__":
    main()