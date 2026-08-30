"""Render small human-readable static forcing trees for selected Lichess puzzles."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forcing_tree_analysis import forcing_children
from forcingness_analysis import board_from_fen, move_features


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_threat_width_500.json"))
    parser.add_argument("--ids", default="qmrOr,2dmkh,7jLWG,TuMM1,T5rPw,Zb1Kf")
    parser.add_argument("--plies", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("data/complexity/forcing_tree_examples.md"))
    return parser.parse_args()


def san(fen: str, move: str) -> str:
    try:
        return pyffish.get_san_moves("chess", fen, [move])[-1]
    except Exception:
        return move


def annotate(fen: str, move: str, solution: str) -> str:
    board = board_from_fen(fen)
    feature = move_features(fen, board, move, fen.split()[1] == "w")
    label = f"{san(fen, move)} ({move}; force={feature['level']})"
    return f"**{label} [solution]**" if move == solution else label


def render_tree(lines: list[str], fen: str, remaining: int, indent: str) -> None:
    if remaining <= 0:
        return
    for move in forcing_children(fen):
        lines.append(f"{indent}- {annotate(fen, move, '')}")
        render_tree(lines, pyffish.get_fen("chess", fen, [move]), remaining - 1, indent + "  ")


def main() -> None:
    args = parse_args()
    requested = [item.strip() for item in args.ids.split(",") if item.strip()]
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = {profile["PuzzleId"]: profile for profile in report["profiles"]}
    lines = ["# Static Forcing-Tree Examples", "", "Each root is the solver position. Only checks/captures are expanded; while in check every legal reply is included. `force=2` capture, `3` check, `4` check-and-capture. This is a diagnostic tree, not an engine PV.", ""]
    for puzzle_id in requested:
        profile = profiles.get(puzzle_id)
        if profile is None:
            lines.extend([f"## {puzzle_id}", "Not present in this sample.", ""])
            continue
        moves = profile["Moves"].split()
        node = profile["nodes"][0]
        solver_fen = pyffish.get_fen("chess", profile["InitialFEN"], moves[: int(node["ply"])])
        solution = node["solution_uci"]
        lines.extend([
            f"## {puzzle_id} ({profile['Rating']})",
            f"FEN: `{solver_fen}`",
            f"Lichess line: `{profile['Moves']}`",
            "",
            "Root forcing candidates:",
        ])
        root_children = forcing_children(solver_fen)
        if solution not in root_children:
            root_children.insert(0, solution)
        for move in root_children:
            lines.append(f"- {annotate(solver_fen, move, solution)}")
            render_tree(lines, pyffish.get_fen("chess", solver_fen, [move]), args.plies, "  ")
        lines.append("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.output} for {len(requested)} requested puzzle(s).")


if __name__ == "__main__":
    main()