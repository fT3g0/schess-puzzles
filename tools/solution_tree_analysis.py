"""Compress Lichess solution branches by whether a defense disrupts the known next plan."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_threat_width_500.json"))
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_move_difficulty_solution_tree_500.json"))
    return parser.parse_args()


def next_solver_move(moves: list[str], solver_ply: int) -> str:
    next_index = solver_ply + 2
    return moves[next_index] if next_index < len(moves) else ""


def enrich(profile: dict) -> dict:
    moves = profile["Moves"].split()
    values = []
    for node in profile["nodes"]:
        solver_ply = int(node["ply"])
        before = pyffish.get_fen("chess", profile["InitialFEN"], moves[:solver_ply])
        solution = node["solution_uci"]
        after_solution = pyffish.get_fen("chess", before, [solution])
        replies = pyffish.legal_moves("chess", after_solution, [])
        continuation = next_solver_move(moves, solver_ply)
        plan_preserving = 0
        plan_breaking = 0
        if continuation:
            for reply in replies:
                reply_fen = pyffish.get_fen("chess", after_solution, [reply])
                if continuation in pyffish.legal_moves("chess", reply_fen, []):
                    plan_preserving += 1
                else:
                    plan_breaking += 1
            # All plan-preserving replies are one practical class; each differing
            # response is retained until a stronger equivalence relation exists.
            classes = (1 if plan_preserving else 0) + plan_breaking
        else:
            classes = 1
        forcing = node.get("forcingness", {})
        metric = {
            "plausible_root_alternatives": forcing.get("plausible_forcing_alternatives", 0),
            "reply_count": len(replies),
            "plan_preserving_replies": plan_preserving,
            "plan_breaking_replies": plan_breaking,
            "defense_equivalence_classes": classes,
            "continuation_known": bool(continuation),
            "solution_tree_bits": round(math.log2(1 + forcing.get("plausible_forcing_alternatives", 0)) + math.log2(max(1, classes)), 3),
        }
        node["solution_tree"] = metric
        values.append(metric)
    mean = lambda key: round(sum(item[key] for item in values) / len(values), 3)
    profile["metrics"].update({
        "mean_root_plausible_forcing_alternatives": mean("plausible_root_alternatives"),
        "mean_defense_equivalence_classes": mean("defense_equivalence_classes"),
        "mean_plan_breaking_replies": mean("plan_breaking_replies"),
        "mean_plan_preserving_replies": mean("plan_preserving_replies"),
        "mean_solution_tree_bits": mean("solution_tree_bits"),
    })
    return profile


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    report["profiles"] = [enrich(profile) for profile in report["profiles"]]
    report["solution_tree_definition"] = {
        "root": "plausible forcing alternatives before the supplied solution, inherited from forcingness_analysis.py",
        "defense": "all legal replies after the supplied solution",
        "equivalence": "replies that preserve the known next solver UCI move form one class; every reply that makes it illegal remains separate",
        "scope": "solution-aware move-execution approximation, not position-evaluation difficulty",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(report['profiles'])} puzzle(s).")


if __name__ == "__main__":
    main()