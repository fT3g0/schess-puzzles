"""Export transparent per-signal diagnostics for Lichess difficulty outliers."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from complexity_composite_analysis import FEATURE_SETS, ORIENTATION, full_coefficients, leave_one_out, zscore
from lichess_complexity_benchmark import rank

DIAGNOSTIC_METRICS = (
    "solver_nodes", "low_depth_decoys", "mean_low_depth_solution_rank",
    "mean_low_depth_near_best", "mean_best_move_switches", "mean_instability_load",
    "mean_solution_forcing", "quiet_solution_fraction", "mean_material_threat_value",
    "mean_more_forcing_legal", "mean_same_forcing_legal",
    "mean_plausible_forcing_alternatives", "mean_directly_refuted_forcing_candidates",
    "mean_reply_branching_bits", "quietness_gap",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_threat_500.json"))
    parser.add_argument("--model", choices=tuple(FEATURE_SETS), default="threat_aware")
    parser.add_argument("--ridge", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=25, help="Outliers per direction.")
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_move_outliers_500.csv"))
    return parser.parse_args()


def percentile(values: np.ndarray) -> np.ndarray:
    return (np.array(rank(values.tolist())) - 1) / max(1, len(values) - 1)


def node_summary(profile: dict) -> str:
    entries = []
    for node in profile.get("nodes", []):
        force = node.get("forcingness", {})
        entries.append(
            f"ply {node['ply']}: solution={node['solution_uci']} low_best={node['low_best_uci']} "
            f"low_rank={node['low_solution_rank']} switches={node['best_move_switches']} "
            f"force={force.get('solution_forcing_level', '?')} higher_force={force.get('more_forcing_legal', '?')} "
            f"plausible={force.get('plausible_forcing_alternatives', '?')} refuted={force.get('directly_refuted_forcing_candidates', '?')}"
        )
    return " | ".join(entries)


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = report["profiles"]
    features = FEATURE_SETS[args.model]
    ratings = np.array([float(profile["Rating"]) for profile in profiles])
    raw = np.array([[float(profile["metrics"][feature]) for feature in features] for profile in profiles])
    standardized, _, _ = zscore(raw)
    coefficients = np.array(full_coefficients(raw, ratings, args.ridge))
    predictions = leave_one_out(raw, ratings, args.ridge)
    residuals = ratings - predictions
    ranking = np.argsort(residuals)
    selected = [*ranking[: args.limit], *ranking[-args.limit :][::-1]]
    percentiles = np.column_stack([percentile(raw[:, index]) for index in range(len(features))])

    fields = [
        "Direction", "PuzzleId", "Rating", "PredictedRating", "Residual", "Themes", "GameUrl",
        "InitialFEN", "Moves", "NodeDiagnostics", *[metric for metric in DIAGNOSTIC_METRICS if metric not in features],
    ]
    for feature in features:
        fields.extend((feature, f"{feature}_percentile", f"{feature}_model_contribution"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in selected:
            profile = profiles[int(index)]
            row = {
                "Direction": "harder_than_model" if residuals[index] > 0 else "easier_than_model",
                "PuzzleId": profile["PuzzleId"],
                "Rating": profile["Rating"],
                "PredictedRating": round(float(predictions[index]), 1),
                "Residual": round(float(residuals[index]), 1),
                "Themes": " ".join(profile.get("Themes", [])),
                "GameUrl": profile.get("GameUrl", ""),
                "InitialFEN": profile.get("InitialFEN", ""),
                "Moves": profile.get("Moves", ""),
                "NodeDiagnostics": node_summary(profile),
                **{metric: profile["metrics"].get(metric, "") for metric in DIAGNOSTIC_METRICS},
            }
            for feature_index, feature in enumerate(features):
                row[feature] = raw[index, feature_index]
                row[f"{feature}_percentile"] = round(float(percentiles[index, feature_index]), 3)
                row[f"{feature}_model_contribution"] = round(float(standardized[index, feature_index] * coefficients[feature_index]), 1)
            writer.writerow(row)
    print(f"Wrote {args.output}: {args.limit} harder and {args.limit} easier outlier(s), model={args.model}.")


if __name__ == "__main__":
    main()