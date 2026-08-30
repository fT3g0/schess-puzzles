"""Estimate a transparent human-visible variant-tree ply budget from saved signals."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forcingness_analysis import VALUES, board_from_fen


DECISIVE_MATERIAL_GAIN = 4
SIMPLIFYING_EXCHANGE_MATERIAL = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_dominance_500.json"))
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_move_difficulty_visible_budget_500.json"))
    return parser.parse_args()


def material_balance(fen: str, solver_white: bool) -> int:
    """Material balance from the solver's side, using orthodox pawn units."""
    balance = 0
    for piece in board_from_fen(fen).values():
        value = VALUES.get(piece.upper(), 0)
        if piece.isupper() == solver_white:
            balance += value
        else:
            balance -= value
    return balance


def material_total(fen: str) -> int:
    return sum(VALUES.get(piece.upper(), 0) for piece in board_from_fen(fen).values())


def continuation_context(profile: dict, node: dict, solution: dict) -> dict:
    """Describe immediate material clarity and simplifying exchanges on the PV."""
    moves = profile["Moves"].split()
    ply = int(node["ply"])
    before = pyffish.get_fen("chess", profile["InitialFEN"], moves[:ply])
    solver_white = before.split()[1] == "w"
    after_solution = pyffish.get_fen("chess", before, [solution["move"]])
    before_balance = material_balance(before, solver_white)
    gain_after_solution = material_balance(after_solution, solver_white) - before_balance
    gain_through_next_solver = gain_after_solution
    material_removed = material_total(before) - material_total(after_solution)
    known_reply = moves[ply + 1] if ply + 1 < len(moves) else ""
    known_next_solver = moves[ply + 2] if ply + 2 < len(moves) else ""
    current = after_solution
    if known_reply:
        current = pyffish.get_fen("chess", current, [known_reply])
        material_removed = material_total(before) - material_total(current)
        gain_through_next_solver = material_balance(current, solver_white) - before_balance
    if known_next_solver:
        current = pyffish.get_fen("chess", current, [known_next_solver])
        material_removed = material_total(before) - material_total(current)
        gain_through_next_solver = material_balance(current, solver_white) - before_balance
    # A simplifying exchange is intentionally narrow: the recorded line must remove
    # major material in the very next exchange sequence. It is a tie-breaker among
    # equally forcing root candidates, never a claim that the position is solved.
    immediate_simplifying_exchange = bool(
        known_reply
        and known_next_solver
        and material_removed >= SIMPLIFYING_EXCHANGE_MATERIAL
    )
    return {
        "material_gain_after_solution": gain_after_solution,
        "material_gain_through_next_solver": gain_through_next_solver,
        "material_removed_through_next_solver": material_removed,
        "decisive_material_gain": max(gain_after_solution, gain_through_next_solver) >= DECISIVE_MATERIAL_GAIN,
        "immediate_simplifying_exchange": immediate_simplifying_exchange,
    }


def enrich(profile: dict) -> dict:
    node_budgets = []
    for node in profile["nodes"]:
        dominance = node["candidate_dominance"]
        solution = dominance.get("solution_candidate") or next(item for item in dominance["top_candidates"] if item["move"] == node["solution_uci"])
        force_floor = max(2, solution["forcing_level"])
        alternatives = [
            item for item in dominance["top_candidates"]
            if item["move"] != solution["move"]
            and item["forcing_level"] >= force_floor
            and not item["directly_refuted"]
        ]
        quick_rejections = [
            item for item in dominance["top_candidates"]
            if item["move"] != solution["move"]
            and item["forcing_level"] >= force_floor
            and item["directly_refuted"]
        ]
        solution_tree = node.get("solution_tree", {})
        continuation_known = bool(solution_tree.get("continuation_known"))
        raw_plan_breaking = int(solution_tree.get("plan_breaking_replies", 0))
        context = continuation_context(profile, node, solution)
        # Once a line has already won at least a rook-equivalent, arbitrary legal
        # replies rarely create a new calculation obligation unless they pose a new
        # concrete threat. That threat test remains future work; for now this is a
        # deliberately conservative material-only collapse.
        effective_plan_breaking = 0 if context["decisive_material_gain"] else raw_plan_breaking
        # A check followed by an immediate major exchange reduces the game state.
        # Human candidate ordering tends to inspect it before same-tier checking
        # moves, so same-tier alternatives no longer count as separate full branches.
        effective_alternatives = [] if context["immediate_simplifying_exchange"] else alternatives
        raw_budget = 1 + int(continuation_known) + 2 * len(alternatives) + len(quick_rejections) + 2 * raw_plan_breaking
        budget = 1 + int(continuation_known) + 2 * len(effective_alternatives) + len(quick_rejections) + 2 * effective_plan_breaking
        metric = {
            "base_solution_plies": 1 + int(continuation_known),
            "plausible_alternative_count": len(alternatives),
            "effective_plausible_alternative_count": len(effective_alternatives),
            "quick_rejection_count": len(quick_rejections),
            "plan_breaking_reply_count": raw_plan_breaking,
            "effective_plan_breaking_reply_count": effective_plan_breaking,
            "raw_visible_ply_budget": raw_budget,
            "visible_ply_budget": budget,
            "alternatives": alternatives,
            "quick_rejections": quick_rejections,
            **context,
        }
        node["visible_tree_budget"] = metric
        node_budgets.append(metric)
    profile["metrics"].update({
        "raw_visible_tree_ply_budget": sum(item["raw_visible_ply_budget"] for item in node_budgets),
        "visible_tree_ply_budget": sum(item["visible_ply_budget"] for item in node_budgets),
        "mean_visible_tree_ply_budget": round(sum(item["visible_ply_budget"] for item in node_budgets) / len(node_budgets), 3),
        "visible_plausible_alternatives": sum(item["effective_plausible_alternative_count"] for item in node_budgets),
        "visible_quick_rejections": sum(item["quick_rejection_count"] for item in node_budgets),
        "visible_plan_breaking_replies": sum(item["effective_plan_breaking_reply_count"] for item in node_budgets),
        "raw_visible_plan_breaking_replies": sum(item["plan_breaking_reply_count"] for item in node_budgets),
    })
    return profile


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    report["profiles"] = [enrich(profile) for profile in report["profiles"]]
    report["visible_tree_budget_definition"] = {
        "base": "one ply for every solver move plus one for its known opponent reply",
        "plausible_alternative": "two plies per non-refuted check/capture-tier alternative",
        "quick_rejection": "one ply per directly refuted candidate",
        "defense": "two plies per defense class that prevents the known next solver move",
        "material_clarity": "plan-breaking replies collapse after a recorded immediate gain of at least four pawn units",
        "reduced_game_state": "same-tier alternatives collapse for a recorded immediate major exchange removing at least eight pawn units",
        "purpose": "transparent experimental proxy for total human-visible calculation, not an engine PV depth",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(report['profiles'])} puzzle(s).")


if __name__ == "__main__":
    main()
