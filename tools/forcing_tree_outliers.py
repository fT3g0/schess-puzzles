"""Render forcing-tree-only difficulty outliers for human inspection."""
from __future__ import annotations

import argparse
import csv
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
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_tree_200.json"))
    parser.add_argument("--predictions", type=Path, default=Path("data/complexity/lichess_move_composite_predictions_tree_200.csv"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("data/complexity/forcing_tree_outliers_200.md"))
    return parser.parse_args()


def san(fen: str, move: str) -> str:
    try:
        return pyffish.get_san_moves("chess", fen, [move])[-1]
    except Exception:
        return move


def display_move(fen: str, move: str, solution: str = "") -> str:
    board = board_from_fen(fen)
    feature = move_features(fen, board, move, fen.split()[1] == "w")
    text = f"{san(fen, move)} ({move}; force={feature['level']})"
    return f"**{text} [solution]**" if move == solution else text


def first_layer(lines: list[str], fen: str, indent: str, solution: str = "") -> None:
    children = forcing_children(fen)
    if not children:
        lines.append(f"{indent}- no forcing child; terminal for this approximation")
        return
    for move in children:
        after = pyffish.get_fen("chess", fen, [move])
        next_children = forcing_children(after)
        label = "all legal replies" if False else "forcing replies"
        # forcing_children itself uses all legal moves only when the side to move is in check.
        lines.append(f"{indent}- {display_move(fen, move, solution)} -> {len(next_children)} next-tree child(ren)")


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = {profile["PuzzleId"]: profile for profile in report["profiles"]}
    with args.predictions.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["model"] == "forcing_tree_only"]
    if not rows:
        raise SystemExit("No forcing_tree_only predictions found. Re-run complexity_composite_analysis.py first.")
    rows.sort(key=lambda row: float(row["Residual"]))
    selected = [*rows[: args.limit], *rows[-args.limit:][::-1]]
    lines = [
        "# Forcing-Tree Prediction Outliers",
        "",
        "## Current Calculation",
        "",
        "For every Lichess solver decision, the current metric starts **after the supplied solution move**. It expands a static tree for at most two more plies and at most 32 nodes. When the side to move is in check, every legal evasion is included; otherwise only checks and captures are included. The per-puzzle values are the means of:",
        "",
        "- `mean_forcing_tree_nodes`: visited tree nodes.",
        "- `mean_forcing_tree_horizon`: deepest reached continuation in plies.",
        "- `mean_forcing_tree_decision_bits`: sum of `log2(children)` at expanded nodes.",
        "",
        "The prediction below uses only these three values in leave-one-out ridge regression. It therefore intentionally exposes where tree size is a poor proxy for human move-finding difficulty.",
        "",
    ]
    for row in selected:
        profile = profiles[row["PuzzleId"]]
        direction = "easier than the tree predicts" if float(row["Residual"]) < 0 else "harder than the tree predicts"
        lines.extend([
            f"## {profile['PuzzleId']} - {direction}",
            "",
            f"- Lichess rating: **{profile['Rating']}**; tree-only prediction: **{row['PredictedRating']}**; residual: **{row['Residual']}**.",
            f"- Themes: `{' '.join(profile.get('Themes', []))}`",
            f"- FEN before the opponent move: `{profile['InitialFEN']}`",
            f"- Lichess line: `{profile['Moves']}`",
            "",
            "Per solver decision:",
        ])
        moves = profile["Moves"].split()
        for node in profile["nodes"]:
            before = pyffish.get_fen("chess", profile["InitialFEN"], moves[: int(node["ply"])])
            after = pyffish.get_fen("chess", before, [node["solution_uci"]])
            tree = node.get("forcing_tree", {})
            lines.append(f"- ply {node['ply']}: solution {display_move(before, node['solution_uci'], node['solution_uci'])}; tree nodes={tree.get('tree_nodes')}, horizon={tree.get('tree_horizon')}, bits={tree.get('tree_decision_bits')}, capped={tree.get('tree_capped')}.")
            lines.append("  - tree immediately after the solution:")
            first_layer(lines, after, "    ")
        lines.append("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.output}: {args.limit} lower and {args.limit} higher tree-only residuals.")


if __name__ == "__main__":
    main()