"""Benchmark regularized gradient boosting for Lichess move-execution ratings.

This is deliberately a combination experiment.  It consumes already-extracted,
human-interpretable features and does not add engine work or change any S-Chess
puzzle data.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lichess_complexity_benchmark import pearson, rank


ALL_FEATURES = (
    "solver_nodes",
    "final_solution_match_rate",
    "low_depth_decoys",
    "mean_low_depth_solution_rank",
    "mean_low_depth_near_best",
    "mean_best_move_switches",
    "mean_instability_load",
    "mean_solution_forcing",
    "quiet_solution_fraction",
    "mean_material_threat_value",
    "mate_threat_fraction",
    "mean_more_forcing_legal",
    "mean_same_forcing_legal",
    "mean_plausible_forcing_alternatives",
    "mean_directly_refuted_forcing_candidates",
    "mean_reply_branching_bits",
    "mean_defense_equivalence_classes",
    "mean_plan_breaking_replies",
    "mean_solution_tree_bits",
    "mean_solution_priority_rank",
    "mean_higher_priority_candidates",
    "mean_solution_priority_margin",
    "mean_solution_material_debt",
    "max_line_material_debt",
    "forcing_plies_while_in_debt",
    "raw_visible_tree_ply_budget",
    "visible_tree_ply_budget",
    "visible_plausible_alternatives",
    "visible_quick_rejections",
    "visible_plan_breaking_replies",
    "raw_visible_plan_breaking_replies",
)
FEATURE_SETS = {
    "core": (
        "solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best",
        "mean_best_move_switches", "mean_instability_load", "low_depth_decoys",
    ),
    "forcing_solution": (
        "solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best",
        "mean_best_move_switches", "mean_instability_load", "low_depth_decoys",
        "mean_solution_forcing", "mean_more_forcing_legal",
        "mean_plausible_forcing_alternatives", "mean_reply_branching_bits",
        "mean_defense_equivalence_classes", "mean_plan_breaking_replies",
        "mean_solution_tree_bits",
    ),
    "human_tree": (
        "solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best",
        "mean_best_move_switches", "mean_instability_load", "low_depth_decoys",
        "mean_solution_forcing", "quiet_solution_fraction", "mean_material_threat_value",
        "mean_more_forcing_legal", "mean_same_forcing_legal",
        "mean_plausible_forcing_alternatives", "mean_directly_refuted_forcing_candidates",
        "mean_reply_branching_bits", "mean_defense_equivalence_classes",
        "mean_plan_breaking_replies", "mean_solution_tree_bits",
        "mean_solution_priority_rank", "mean_higher_priority_candidates",
        "mean_solution_priority_margin", "solution_top_priority_fraction",
        "mean_solution_priority_tier_size", "visible_tree_ply_budget",
        "visible_plausible_alternatives", "visible_quick_rejections",
        "visible_plan_breaking_replies",
    ),
    "transition": (
        "solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best",
        "mean_best_move_switches", "mean_instability_load", "low_depth_decoys",
        "mean_solution_forcing", "mean_more_forcing_legal",
        "mean_plausible_forcing_alternatives", "mean_reply_branching_bits",
        "mean_defense_equivalence_classes", "mean_plan_breaking_replies",
        "mean_solution_tree_bits", "solution_top_priority_fraction",
        "mean_solution_priority_tier_size", "mean_root_material_balance",
        "mean_root_material_deficit", "mean_tempo_threat_delta_cp",
        "tempo_mate_threat_fraction", "mean_solution_eval_delta_cp",
        "mean_reply_eval_delta_cp", "mean_continuation_eval_delta_cp",
        "mean_continuation_material_delta", "conversion_fraction",
        "top_priority_conversion_fraction",
        "mean_post_continuation_forcing_count",
        "mean_candidate_tree_alternatives",
        "candidate_tree_refuted_fraction",
        "candidate_tree_live_fraction",
        "candidate_tree_conversion_fraction",
        "mean_candidate_tree_reply_width",
        "mean_candidate_tree_reply_forcing",
        "mean_candidate_tree_continuation_forcing",
        "mean_candidate_tree_refutation_gap_cp",
    ),    "all": ALL_FEATURES,
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=Path("data/complexity/lichess_move_difficulty_visible_budget_500.json"),
    )
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--max-iter", type=int, default=100)
    parser.add_argument("--max-leaf-nodes", type=int, default=7)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--l2", type=float, default=10.0)
    parser.add_argument("--feature-set", choices=sorted(FEATURE_SETS), default="forcing_solution")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/complexity/lichess_gradient_boost_500.json"),
    )
    parser.add_argument(
        "--prediction-output",
        type=Path,
        default=Path("data/complexity/lichess_gradient_boost_predictions_500.csv"),
    )
    return parser.parse_args()


def game_group(profile: dict) -> str:
    """Keep multiple sampled puzzles from the same Lichess game in one fold."""
    url = str(profile.get("GameUrl") or "").strip()
    return url.rsplit("/", 1)[-1] if url else profile["PuzzleId"]


def spearman(values: np.ndarray, ratings: np.ndarray) -> float | None:
    return pearson(rank(values.tolist()), rank(ratings.tolist()))


def fold_model(args: argparse.Namespace) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        learning_rate=args.learning_rate,
        max_iter=args.max_iter,
        max_leaf_nodes=args.max_leaf_nodes,
        l2_regularization=args.l2,
        early_stopping=False,
        random_state=20260716,
    )


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    features = FEATURE_SETS[args.feature_set]
    profiles = [
        profile
        for profile in report["profiles"]
        if all(feature in profile["metrics"] for feature in features)
    ]
    if len(profiles) < args.folds:
        raise SystemExit(f"Need at least {args.folds} complete profiles; found {len(profiles)}.")

    x = np.array([[float(profile["metrics"][feature]) for feature in features] for profile in profiles])
    ratings = np.array([float(profile["Rating"]) for profile in profiles])
    groups = np.array([game_group(profile) for profile in profiles])
    folds = min(args.folds, len(set(groups)))
    splitter = GroupKFold(n_splits=folds)
    predictions = np.zeros(len(profiles))
    fold_scores = []
    importances: list[np.ndarray] = []

    for fold, (train, test) in enumerate(splitter.split(x, ratings, groups), start=1):
        model = fold_model(args)
        model.fit(x[train], ratings[train])
        predictions[test] = model.predict(x[test])
        fold_scores.append({
            "fold": fold,
            "train": int(len(train)),
            "test": int(len(test)),
            "spearman": spearman(predictions[test], ratings[test]),
        })
        importance = permutation_importance(
            model,
            x[test],
            ratings[test],
            scoring="neg_mean_absolute_error",
            n_repeats=12,
            random_state=20260716 + fold,
        )
        importances.append(importance.importances_mean)

    overall = {
        "pearson": pearson(predictions.tolist(), ratings.tolist()),
        "spearman": spearman(predictions, ratings),
        "mean_absolute_error": round(float(np.mean(np.abs(predictions - ratings))), 2),
    }
    mean_importance = np.mean(importances, axis=0)
    feature_importance = [
        {"feature": feature, "permutation_mae_increase": round(float(value), 3)}
        for feature, value in sorted(zip(features, mean_importance), key=lambda item: item[1], reverse=True)
    ]
    output = {
        "definition": "Lichess move-execution difficulty; grouped gradient-boosting benchmark",
        "source": str(args.input),
        "profiles": len(profiles),
        "games": len(set(groups)),
        "feature_set": args.feature_set,
        "features": list(features),
        "parameters": {
            "folds": folds,
            "max_iter": args.max_iter,
            "max_leaf_nodes": args.max_leaf_nodes,
            "learning_rate": args.learning_rate,
            "l2_regularization": args.l2,
        },
        "overall": overall,
        "folds": fold_scores,
        "feature_importance": feature_importance,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    with args.prediction_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["PuzzleId", "Game", "Rating", "PredictedRating", "Residual"])
        writer.writeheader()
        for profile, group, prediction in zip(profiles, groups, predictions):
            writer.writerow({
                "PuzzleId": profile["PuzzleId"],
                "Game": group,
                "Rating": profile["Rating"],
                "PredictedRating": round(float(prediction), 1),
                "Residual": round(float(profile["Rating"] - prediction), 1),
            })

    print(
        "Gradient boost grouped CV: "
        f"Spearman={overall['spearman']}, Pearson={overall['pearson']}, MAE={overall['mean_absolute_error']}"
    )
    print("Top permutation importances:")
    for item in feature_importance[:12]:
        print(f"  {item['feature']}: +{item['permutation_mae_increase']} MAE")
    print(f"Wrote {args.output} and {args.prediction_output}.")


if __name__ == "__main__":
    main()
