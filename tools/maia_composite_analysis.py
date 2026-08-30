"""Test whether Maia move-choice signals add to human-readable difficulty features.

This keeps all samples from one Lichess game in the same validation fold.  Maia
is evaluated only on standard chess; the purpose is to identify abstract signals
worth re-implementing for S-Chess, not to use Maia directly in production.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lichess_complexity_benchmark import pearson, rank


BASE_FEATURES = (
    "solver_nodes",
    "mean_low_depth_solution_rank",
    "mean_low_depth_near_best",
    "mean_best_move_switches",
    "mean_instability_load",
    "low_depth_decoys",
    "mean_solution_forcing",
    "mean_more_forcing_legal",
    "mean_plausible_forcing_alternatives",
    "mean_reply_branching_bits",
    "mean_defense_equivalence_classes",
    "mean_plan_breaking_replies",
    "mean_solution_tree_bits",
)
MAIA_FEATURES = (
    "maia_min_log_probability_1200",
    "maia_mean_log_probability_1200",
    "maia_mean_solution_rank_1200",
    "maia_mean_gap_to_top1_1200",
    "maia_top1_fraction_1200",
    "maia_mean_entropy_1200",
)
DERIVED_MAIA_FEATURES = (
    "maia_mean_log_probability_gain_800_to_1600",
    "maia_min_log_probability_gain_800_to_1600",
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
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_maia_composites_500.json"))
    return parser.parse_args()


def game_group(profile: dict) -> str:
    url = str(profile.get("GameUrl") or "").strip()
    return url.rsplit("/", 1)[-1] if url else str(profile["PuzzleId"])


def correlation(values: np.ndarray, ratings: np.ndarray) -> dict[str, float | None]:
    return {
        "pearson": pearson(values.tolist(), ratings.tolist()),
        "spearman": pearson(rank(values.tolist()), rank(ratings.tolist())),
    }


def feature_row(base: dict, maia: dict) -> dict[str, float]:
    row = {name: float(base["metrics"][name]) for name in BASE_FEATURES}
    metrics = maia["metrics"]
    row.update({name: float(metrics[name]) for name in MAIA_FEATURES})
    for prefix in ("maia_mean_log_probability", "maia_min_log_probability"):
        row[f"{prefix}_gain_800_to_1600"] = float(metrics[f"{prefix}_1600"]) - float(metrics[f"{prefix}_800"])
    return row


def ridge_prediction(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, ridge: float) -> np.ndarray:
    mean = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale = np.where(scale == 0, 1.0, scale)
    normalized = (train_x - mean) / scale
    centered = train_y - train_y.mean()
    coefficients = np.linalg.solve(
        normalized.T @ normalized + ridge * np.eye(normalized.shape[1]),
        normalized.T @ centered,
    )
    return ((test_x - mean) / scale) @ coefficients + train_y.mean()


def grouped_ridge(x: np.ndarray, ratings: np.ndarray, groups: np.ndarray, folds: int, ridge: float) -> tuple[np.ndarray, list[dict]]:
    splitter = GroupKFold(n_splits=min(folds, len(set(groups))))
    predictions = np.zeros(len(ratings))
    scores = []
    for index, (train, test) in enumerate(splitter.split(x, ratings, groups), start=1):
        predictions[test] = ridge_prediction(x[train], ratings[train], x[test], ridge)
        scores.append({
            "fold": index,
            "train": int(len(train)),
            "test": int(len(test)),
            "spearman": correlation(predictions[test], ratings[test])["spearman"],
        })
    return predictions, scores


def main() -> None:
    args = parse_args()
    base_profiles = {profile["PuzzleId"]: profile for profile in json.loads(args.base_input.read_text(encoding="utf-8"))["profiles"]}
    maia_profiles = {profile["PuzzleId"]: profile for profile in json.loads(args.maia_input.read_text(encoding="utf-8"))["profiles"]}
    ids = [puzzle_id for puzzle_id in base_profiles if puzzle_id in maia_profiles]
    rows = []
    for puzzle_id in ids:
        base, maia = base_profiles[puzzle_id], maia_profiles[puzzle_id]
        if any(feature not in base["metrics"] for feature in BASE_FEATURES):
            continue
        if any(feature not in maia["metrics"] for feature in MAIA_FEATURES):
            continue
        rows.append((base, feature_row(base, maia)))
    ratings = np.array([float(base["Rating"]) for base, _ in rows])
    groups = np.array([game_group(base) for base, _ in rows])
    sets = {
        "maia_only": MAIA_FEATURES,
        "maia_with_skill_curve": MAIA_FEATURES + DERIVED_MAIA_FEATURES,
        "forcing_solution_baseline": BASE_FEATURES,
        "forcing_solution_plus_maia": BASE_FEATURES + MAIA_FEATURES,
        "forcing_solution_plus_maia_curve": BASE_FEATURES + MAIA_FEATURES + DERIVED_MAIA_FEATURES,
    }
    results = {}
    for name, features in sets.items():
        x = np.array([[row[feature] for feature in features] for _, row in rows])
        predictions, folds = grouped_ridge(x, ratings, groups, args.folds, args.ridge)
        results[name] = {
            "features": list(features),
            "grouped_ridge": correlation(predictions, ratings),
            "folds": folds,
        }
    output = {
        "definition": "Grouped cross-validated Ridge comparison of Maia human move-choice and handcrafted move-execution features.",
        "base_input": str(args.base_input),
        "maia_input": str(args.maia_input),
        "profiles": len(rows),
        "games": len(set(groups)),
        "ridge": args.ridge,
        "models": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("Grouped Ridge Spearman correlations:")
    for name, result in results.items():
        print(f"  {name}: {result['grouped_ridge']['spearman']}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
