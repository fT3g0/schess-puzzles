"""Add human-priority candidate dominance and material-debt signals to Lichess lines."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forcingness_analysis import VALUES, board_from_fen, captured_value, move_features


MAX_PRIORITY_CANDIDATES = 12


def direct_recaptures(after_fen: str, target: str) -> list[str]:
    return [reply for reply in pyffish.legal_moves("chess", after_fen, []) if reply[2:4] == target]


def sacrifice_has_forcing_compensation(after_fen: str, recaptures: list[str], debt: int) -> bool:
    """Keep a sacrifice plausible if every immediate recapture has a forcing answer.

    A full material recovery is enough; a check is retained as a live tactical branch
    because it may be a mating or deflection continuation beyond this two-ply probe.
    """
    if not recaptures:
        return False
    for reply in recaptures:
        position = pyffish.get_fen("chess", after_fen, [reply])
        board = board_from_fen(position)
        white = position.split()[1] == "w"
        continuations = [move_features(position, board, move, white) for move in pyffish.legal_moves("chess", position, [])]
        if not any(item["captured_value"] >= debt or item["level"] >= 3 for item in continuations):
            return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_solution_tree_500.json"))
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_move_difficulty_dominance_500.json"))
    return parser.parse_args()


def candidate_record(fen: str, board: dict[str, str], move: str, white: bool) -> dict:
    feature = move_features(fen, board, move, white)
    moved_piece = feature["after_board"][move[2:4]]
    moved_value = VALUES.get(moved_piece.upper(), 0)
    potential_loss = max(0, moved_value - feature["captured_value"])
    # Only a forcing move with a possible material deficit needs the expensive legal
    # recapture probe. Quiet moves never gain priority from this test.
    direct_refutation = False
    temporary_sacrifice = False
    if feature["level"] >= 2 and potential_loss >= 2:
        after_fen = pyffish.get_fen("chess", fen, [move])
        recaptures = direct_recaptures(after_fen, move[2:4])
        if recaptures:
            temporary_sacrifice = True
            direct_refutation = not sacrifice_has_forcing_compensation(after_fen, recaptures, potential_loss)
    material_debt = potential_loss if direct_refutation else 0
    # Primary ordering is forcingness. Safety only breaks ties within a forcing tier:
    # a speculative check/capture remains ahead of a quiet move.
    priority = feature["level"] * 100 + (8 if not direct_refutation else 0) - min(20, material_debt)
    return {
        "move": move,
        "forcing_level": feature["level"],
        "captured_value": feature["captured_value"],
        "material_debt": material_debt,
        "directly_refuted": direct_refutation,
        "priority": priority,
    }


def line_debt(profile: dict, solver_white: bool) -> dict:
    moves = profile["Moves"].split()
    # The initial opponent move created the solver position; it is not part of the
    # player's tactical solution and must not count as a sacrifice debt.
    fen = pyffish.get_fen("chess", profile["InitialFEN"], moves[:1])
    moves = moves[1:]
    balance = 0
    max_debt = 0
    forcing_while_in_debt = 0
    for move in moves:
        board = board_from_fen(fen)
        mover_white = fen.split()[1] == "w"
        captured = captured_value(board, fen, move)
        if mover_white == solver_white:
            balance += captured
            feature = move_features(fen, board, move, mover_white)
            if balance < 0 and feature["level"] >= 2:
                forcing_while_in_debt += 1
        else:
            balance -= captured
        max_debt = max(max_debt, -balance)
        fen = pyffish.get_fen("chess", fen, [move])
    return {"max_line_material_debt": max_debt, "final_line_material_balance": balance, "forcing_plies_while_in_debt": forcing_while_in_debt}


def enrich(profile: dict) -> dict:
    moves = profile["Moves"].split()
    node_values = []
    for node in profile["nodes"]:
        ply = int(node["ply"])
        fen = pyffish.get_fen("chess", profile["InitialFEN"], moves[:ply])
        board = board_from_fen(fen)
        white = fen.split()[1] == "w"
        records = [candidate_record(fen, board, move, white) for move in pyffish.legal_moves("chess", fen, [])]
        records.sort(key=lambda item: (-item["priority"], item["move"]))
        solution = next(item for item in records if item["move"] == node["solution_uci"])
        highest_priority = records[0]["priority"]
        higher_priority = sum(item["priority"] > solution["priority"] for item in records)
        priority_tier_size = sum(item["priority"] == solution["priority"] for item in records)
        next_priority = max((item["priority"] for item in records if item["priority"] < solution["priority"]), default=solution["priority"])
        node_metric = {
            # Ties are deliberately kept as one human candidate tier. Sorting order
            # inside a tier is arbitrary and must not turn into fake difficulty.
            "solution_priority_rank": higher_priority + 1,
            "higher_priority_candidates": higher_priority,
            "solution_top_priority": solution["priority"] == highest_priority,
            "solution_priority_tier_size": priority_tier_size,
            "solution_priority_margin": solution["priority"] - next_priority if higher_priority == 0 else 0,
            "solution_material_debt": solution["material_debt"],
            "solution_directly_refuted": solution["directly_refuted"],
            "solution_candidate": solution,
            "top_candidates": records[:MAX_PRIORITY_CANDIDATES],
        }
        node["candidate_dominance"] = node_metric
        node_values.append(node_metric)
    solver_white = pyffish.get_fen("chess", profile["InitialFEN"], moves[: int(profile["nodes"][0]["ply"])]).split()[1] == "w"
    debt = line_debt(profile, solver_white)
    mean = lambda key: round(sum(item[key] for item in node_values) / len(node_values), 3)
    profile["metrics"].update({
        "mean_solution_priority_rank": mean("solution_priority_rank"),
        "mean_higher_priority_candidates": mean("higher_priority_candidates"),
        "solution_top_priority_fraction": round(sum(item["solution_top_priority"] for item in node_values) / len(node_values), 3),
        "mean_solution_priority_tier_size": mean("solution_priority_tier_size"),
        "mean_solution_priority_margin": mean("solution_priority_margin"),
        "mean_solution_material_debt": mean("solution_material_debt"),
        **debt,
    })
    return profile


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    report["profiles"] = [enrich(profile) for profile in report["profiles"]]
    report["candidate_dominance_definition"] = {
        "priority": "forcingness is primary (check-capture > check > capture > threat > quiet); safety only breaks ties within a tier",
        "material_debt": "potential loss only when the moved piece is immediately legally recaptured; otherwise zero",
        "direct_refutation": "every immediate recapture lacks a material recovery or checking continuation within two plies",
        "line_debt": "material balance of the solver side after the opponent move that creates the puzzle position",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(report['profiles'])} puzzle(s).")


if __name__ == "__main__":
    main()