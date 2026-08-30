"""Render human-visible ply-budget outliers for manual calibration."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_visible_budget_500.json"))
    parser.add_argument("--predictions", type=Path, default=Path("data/complexity/lichess_move_composite_predictions_visible_budget_500.csv"))
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--output", type=Path, default=Path("data/complexity/visible_tree_budget_outliers_500.md"))
    return parser.parse_args()


def candidate_label(item: dict) -> str:
    flags = []
    if item.get("temporary_sacrifice"):
        flags.append("temporary sacrifice")
    if item.get("directly_refuted"):
        flags.append("quick rejection")
    suffix = f", {', '.join(flags)}" if flags else ""
    return f"`{item['move']}` force={item['forcing_level']}, priority={item['priority']}{suffix}"


def node_context_label(budget: dict) -> str:
    flags = []
    if budget.get("immediate_simplifying_exchange"):
        flags.append("same-tier alternatives suppressed after immediate major exchange")
    if budget.get("decisive_material_gain"):
        flags.append("plan-breaking replies suppressed after decisive material gain")
    if not flags:
        return "none"
    return "; ".join(flags)


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = {profile["PuzzleId"]: profile for profile in report["profiles"]}
    with args.predictions.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["model"] == "visible_tree_aware"]
    if not rows:
        raise SystemExit("No visible_tree_aware predictions. Run complexity_composite_analysis.py first.")
    rows.sort(key=lambda row: float(row["Residual"]))
    selected = [*rows[: args.limit], *rows[-args.limit:][::-1]]
    lines = [
        "# Human-Visible Variant-Tree Budget Outliers", "",
        "Raw budget per solver decision: `1` for the solver move, `+1` for its known opponent reply, `+2` for each non-refuted forcing-tier alternative, `+1` for each quickly rejected candidate, and `+2` for each defense class that prevents the known next solver move.",
        "",
        "The effective budget additionally suppresses same-tier alternatives after a recorded immediate major exchange, and suppresses plan-breaking replies after a recorded gain of at least four pawn units. Both suppressions are experimental and displayed explicitly below.",
        "",
        "The prediction uses the full visible-tree-aware composite, not this budget alone. Inspect whether the effective budget resembles the number of plies a human would seriously calculate.", "",
    ]
    for row in selected:
        profile = profiles[row["PuzzleId"]]
        direction = "easier than predicted" if float(row["Residual"]) < 0 else "harder than predicted"
        metrics = profile["metrics"]
        lines.extend([
            f"## {profile['PuzzleId']} - {direction}", "",
            f"- Rating: **{profile['Rating']}**; prediction: **{row['PredictedRating']}**; residual: **{row['Residual']}**.",
            f"- Effective / raw visible ply budget: **{metrics['visible_tree_ply_budget']} / {metrics['raw_visible_tree_ply_budget']}**; effective plausible alternatives: **{metrics['visible_plausible_alternatives']}**; effective plan-breaking replies: **{metrics['visible_plan_breaking_replies']} / {metrics['raw_visible_plan_breaking_replies']} raw**.",
            f"- Themes: `{' '.join(profile.get('Themes', []))}`",
            f"- FEN before opponent move: `{profile['InitialFEN']}`",
            f"- Lichess line: `{profile['Moves']}`", "",
        ])
        for node in profile["nodes"]:
            budget = node["visible_tree_budget"]
            lines.append(
                f"- ply {node['ply']} / solution `{node['solution_uci']}`: effective / raw **{budget['visible_ply_budget']} / {budget['raw_visible_ply_budget']}**; "
                f"base {budget['base_solution_plies']}, alternatives {budget['effective_plausible_alternative_count']} / {budget['plausible_alternative_count']}, "
                f"quick rejections {budget['quick_rejection_count']}, plan-breaking replies {budget['effective_plan_breaking_reply_count']} / {budget['plan_breaking_reply_count']}."
            )
            lines.append(
                f"  - PV material: gain after move {budget['material_gain_after_solution']:+}; gain through next solver move {budget['material_gain_through_next_solver']:+}; material removed {budget['material_removed_through_next_solver']}; suppression: {node_context_label(budget)}."
            )
            if budget["alternatives"]:
                lines.append("  - raw alternatives: " + "; ".join(candidate_label(item) for item in budget["alternatives"]))
            if budget["quick_rejections"]:
                lines.append("  - quick rejections: " + "; ".join(candidate_label(item) for item in budget["quick_rejections"]))
        lines.append("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.output}: {args.limit} lower and {args.limit} higher residuals.")


if __name__ == "__main__":
    main()
