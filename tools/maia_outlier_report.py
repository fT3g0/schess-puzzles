"""Write Maia-vs-baseline residual examples for manual difficulty inspection.

The report uses the same grouped Ridge protocol as ``maia_composite_analysis``.
It identifies positions where Maia's human move-choice distribution helps or
hurts the existing forcing/solution-aware feature baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maia_composite_analysis import (
    BASE_FEATURES,
    MAIA_FEATURES,
    feature_row,
    game_group,
    grouped_ridge,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-input",
        type=Path,
        default=Path("data/complexity/lichess_move_difficulty_visible_budget_500.json"),
    )
    parser.add_argument(
        "--maia-input",
        type=Path,
        default=Path("data/complexity/lichess_maia_probe_500.json"),
    )
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--ridge", type=float, default=20.0)
    parser.add_argument("--examples", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("data/complexity/maia_baseline_outliers_500.md"))
    return parser.parse_args()


def format_case(case: dict) -> str:
    profile = case["profile"]
    metrics = case["features"]
    return "\n".join([
        f"### {profile['PuzzleId']} | rating {int(profile['Rating'])} | improvement {case['improvement']:+.0f} MAE",
        f"- Lichess: {profile.get('GameUrl') or 'unknown'}",
        f"- Baseline prediction: {case['baseline_prediction']:.0f}; Maia prediction: {case['combined_prediction']:.0f}.",
        f"- Themes: {' '.join(profile.get('Themes') or [])}",
        f"- Maia-1200: min log p={metrics['maia_min_log_probability_1200']:.3f}, mean log p={metrics['maia_mean_log_probability_1200']:.3f}, mean rank={metrics['maia_mean_solution_rank_1200']:.2f}, top-1={metrics['maia_top1_fraction_1200']:.2f}, gap={metrics['maia_mean_gap_to_top1_1200']:.3f}, entropy={metrics['maia_mean_entropy_1200']:.3f}.",
        f"- Existing signals: solver nodes={metrics['solver_nodes']:.0f}, forcing={metrics['mean_solution_forcing']:.2f}, plausible forcing alternatives={metrics['mean_plausible_forcing_alternatives']:.2f}, best-move switches={metrics['mean_best_move_switches']:.2f}, solution-tree bits={metrics['mean_solution_tree_bits']:.2f}.",
        f"- FEN: `{profile['InitialFEN']}`",
        f"- Line: `{profile['Moves']}`",
    ])


def main() -> None:
    args = parse_args()
    base = {item["PuzzleId"]: item for item in json.loads(args.base_input.read_text(encoding="utf-8"))["profiles"]}
    maia = {item["PuzzleId"]: item for item in json.loads(args.maia_input.read_text(encoding="utf-8"))["profiles"]}
    rows = []
    for puzzle_id, profile in base.items():
        maia_profile = maia.get(puzzle_id)
        if not maia_profile or any(name not in profile["metrics"] for name in BASE_FEATURES):
            continue
        if any(name not in maia_profile["metrics"] for name in MAIA_FEATURES):
            continue
        rows.append((profile, feature_row(profile, maia_profile)))
    ratings = np.array([float(profile["Rating"]) for profile, _ in rows])
    groups = np.array([game_group(profile) for profile, _ in rows])
    baseline_x = np.array([[row[name] for name in BASE_FEATURES] for _, row in rows])
    combined_x = np.array([[row[name] for name in (*BASE_FEATURES, *MAIA_FEATURES)] for _, row in rows])
    baseline, _ = grouped_ridge(baseline_x, ratings, groups, args.folds, args.ridge)
    combined, _ = grouped_ridge(combined_x, ratings, groups, args.folds, args.ridge)
    cases = []
    for (profile, features), actual, base_prediction, combined_prediction in zip(rows, ratings, baseline, combined):
        base_error = abs(actual - base_prediction)
        combined_error = abs(actual - combined_prediction)
        cases.append({
            "profile": profile,
            "features": features,
            "baseline_prediction": float(base_prediction),
            "combined_prediction": float(combined_prediction),
            "improvement": float(base_error - combined_error),
        })
    helped = sorted(cases, key=lambda item: item["improvement"], reverse=True)[: args.examples]
    hurt = sorted(cases, key=lambda item: item["improvement"])[: args.examples]
    document = [
        "# Maia vs Baseline Outliers",
        "",
        "Improvement is the reduction in absolute rating error when Maia features are added to the grouped cross-validated forcing/solution-aware Ridge baseline. Positive values mean Maia helped.",
        "",
        "## Maia Helped Most",
        "",
        *[format_case(case) + "\n" for case in helped],
        "## Maia Hurt Most",
        "",
        *[format_case(case) + "\n" for case in hurt],
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(document), encoding="utf-8")
    print(f"Wrote {args.output} with {len(helped)} helped and {len(hurt)} hurt examples.")


if __name__ == "__main__":
    main()
