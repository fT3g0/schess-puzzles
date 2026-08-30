"""Compare composite move-execution difficulty signals with leakage-resistant validation."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lichess_complexity_benchmark import pearson, rank

ORIENTATION = {"mean_solution_forcing": -1.0, "mean_material_threat_value": -1.0, "mate_threat_fraction": -1.0}

FEATURE_SETS = {
    "ambiguity": ("mean_low_depth_solution_rank", "mean_low_depth_near_best"),
    "instability": ("mean_best_move_switches", "mean_instability_load"),
    "core": ("mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load"),
    "core_plus_decoys": ("mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load", "low_depth_decoys"),
    "all_execution": ("solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load", "low_depth_decoys"),
    "forcing_aware": ("solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load", "low_depth_decoys", "mean_solution_forcing", "mean_more_forcing_legal", "mean_plausible_forcing_alternatives", "mean_reply_branching_bits"),
    "visible_tree_aware": ("solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load", "low_depth_decoys", "mean_solution_forcing", "mean_more_forcing_legal", "mean_plausible_forcing_alternatives", "mean_reply_branching_bits", "mean_defense_equivalence_classes", "mean_plan_breaking_replies", "visible_tree_ply_budget", "visible_plausible_alternatives", "visible_quick_rejections", "visible_plan_breaking_replies"),
    "dominance_aware": ("solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load", "low_depth_decoys", "mean_solution_forcing", "mean_more_forcing_legal", "mean_plausible_forcing_alternatives", "mean_reply_branching_bits", "mean_defense_equivalence_classes", "mean_plan_breaking_replies", "mean_solution_priority_rank", "mean_higher_priority_candidates", "mean_solution_priority_margin", "mean_solution_material_debt", "max_line_material_debt", "forcing_plies_while_in_debt"),
    "forcing_solution_aware": ("solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load", "low_depth_decoys", "mean_solution_forcing", "mean_more_forcing_legal", "mean_plausible_forcing_alternatives", "mean_reply_branching_bits", "mean_defense_equivalence_classes", "mean_plan_breaking_replies", "mean_solution_tree_bits"),
    "solution_aware": ("solver_nodes", "mean_low_depth_solution_rank", "mean_best_move_switches", "mean_root_plausible_forcing_alternatives", "mean_defense_equivalence_classes", "mean_plan_breaking_replies", "mean_solution_tree_bits"),
    "forcing_tree_only": ("mean_forcing_tree_nodes", "mean_forcing_tree_horizon", "mean_forcing_tree_decision_bits"),
    "tree_aware": ("solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load", "low_depth_decoys", "mean_solution_forcing", "mean_more_forcing_legal", "mean_plausible_forcing_alternatives", "mean_reply_branching_bits", "mean_forcing_tree_nodes", "mean_forcing_tree_horizon", "mean_forcing_tree_decision_bits"),
    "threat_aware": ("solver_nodes", "mean_low_depth_solution_rank", "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load", "low_depth_decoys", "mean_solution_forcing", "mean_material_threat_value", "mate_threat_fraction", "mean_more_forcing_legal", "mean_plausible_forcing_alternatives", "mean_reply_branching_bits", "mean_forcing_tree_nodes", "mean_forcing_tree_horizon", "mean_forcing_tree_decision_bits"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_25.json"))
    parser.add_argument("--ridge", type=float, default=1.0, help="Regularization for standardized ridge regression.")
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_move_composites.json"))
    parser.add_argument("--prediction-output", type=Path, default=Path("data/complexity/lichess_move_composite_predictions.csv"))
    return parser.parse_args()


def correlation(values: np.ndarray, ratings: np.ndarray) -> dict[str, float | None]:
    value_list, rating_list = values.tolist(), ratings.tolist()
    return {"pearson": pearson(value_list, rating_list), "spearman": pearson(rank(value_list), rank(rating_list))}


def zscore(values: np.ndarray, mean: np.ndarray | None = None, scale: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = values.mean(axis=0) if mean is None else mean
    scale = values.std(axis=0) if scale is None else scale
    scale = np.where(scale == 0, 1.0, scale)
    return (values - mean) / scale, mean, scale


def ridge_predict(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, regularization: float) -> float:
    standardized, mean, scale = zscore(train_x)
    centered_y = train_y - train_y.mean()
    identity = np.eye(standardized.shape[1])
    coefficients = np.linalg.solve(standardized.T @ standardized + regularization * identity, standardized.T @ centered_y)
    return float(((test_x - mean) / scale) @ coefficients + train_y.mean())


def leave_one_out(x: np.ndarray, ratings: np.ndarray, regularization: float) -> np.ndarray:
    predictions = []
    for index in range(len(ratings)):
        mask = np.ones(len(ratings), dtype=bool)
        mask[index] = False
        predictions.append(ridge_predict(x[mask], ratings[mask], x[index], regularization))
    return np.array(predictions)


def full_coefficients(x: np.ndarray, ratings: np.ndarray, regularization: float) -> list[float]:
    standardized, _, _ = zscore(x)
    centered_y = ratings - ratings.mean()
    return np.linalg.solve(standardized.T @ standardized + regularization * np.eye(x.shape[1]), standardized.T @ centered_y).round(3).tolist()


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = report["profiles"]
    ratings = np.array([float(profile["Rating"]) for profile in profiles])
    results: dict[str, dict] = {}
    prediction_rows: list[dict] = []
    for name, features in FEATURE_SETS.items():
        if any(feature not in profile["metrics"] for profile in profiles for feature in features):
            continue
        x = np.array([[float(profile["metrics"][feature]) for feature in features] for profile in profiles])
        orientation = np.array([ORIENTATION.get(feature, 1.0) for feature in features])
        equal_score = (zscore(x)[0] * orientation).mean(axis=1)
        predictions = leave_one_out(x, ratings, args.ridge)
        results[name] = {
            "features": features,
            "equal_weight": correlation(equal_score, ratings),
            "ridge_leave_one_out": correlation(predictions, ratings),
            "standardized_ridge_coefficients": dict(zip(features, full_coefficients(x, ratings, args.ridge))),
        }
        for profile, prediction in zip(profiles, predictions):
            prediction_rows.append({"model": name, "PuzzleId": profile["PuzzleId"], "Rating": profile["Rating"], "PredictedRating": round(float(prediction), 1), "Residual": round(float(profile["Rating"] - prediction), 1)})
    output = {"source": str(args.input), "sample_size": len(profiles), "ridge": args.ridge, "models": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    with args.prediction_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model", "PuzzleId", "Rating", "PredictedRating", "Residual"])
        writer.writeheader()
        writer.writerows(prediction_rows)
    print("Composite correlations with Lichess rating (equal-weight / ridge LOOCV Spearman):")
    for name, result in results.items():
        print(f"  {name}: {result['equal_weight']['spearman']} / {result['ridge_leave_one_out']['spearman']}")
    print(f"Wrote {args.output} and {args.prediction_output}.")


if __name__ == "__main__":
    main()