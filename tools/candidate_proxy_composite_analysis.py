"""Benchmark transferable human-candidate proxy features beside Maia and baseline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lichess_complexity_benchmark import pearson, rank
from maia_composite_analysis import BASE_FEATURES, MAIA_FEATURES, feature_row, game_group, grouped_ridge


THREAT_TREE_FEATURES = (
    "mean_active_threat_candidates",
    "mean_quick_refutation_decoys",
    "mean_quick_refutation_value",
    "solution_certified_material_threat_fraction",
)

PROXY_FEATURES = (
    "proxy_min_log_probability",
    "proxy_mean_log_probability",
    "proxy_mean_solution_priority_rank",
    "proxy_mean_solution_sorted_rank",
    "proxy_top_priority_fraction",
    "proxy_mean_gap_to_top1",
    "proxy_mean_entropy",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-input", type=Path, default=Path("data/complexity/lichess_move_difficulty_visible_budget_500.json"))
    parser.add_argument("--maia-input", type=Path, default=Path("data/complexity/lichess_maia_probe_500.json"))
    parser.add_argument("--proxy-input", type=Path, default=Path("data/complexity/lichess_human_candidate_proxy_500.json"))
    parser.add_argument("--ridge", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_candidate_proxy_composites_500.json"))
    return parser.parse_args()


def score(predictions: np.ndarray, ratings: np.ndarray) -> dict[str, float]:
    return {
        "spearman": round(float(pearson(rank(predictions.tolist()), rank(ratings.tolist()))), 3),
        "pearson": round(float(pearson(predictions.tolist(), ratings.tolist())), 3),
        "mae": round(float(np.mean(np.abs(predictions - ratings))), 1),
    }


def main() -> None:
    args = parse_args()
    base = {item["PuzzleId"]: item for item in json.loads(args.base_input.read_text(encoding="utf-8"))["profiles"]}
    maia = {item["PuzzleId"]: item for item in json.loads(args.maia_input.read_text(encoding="utf-8"))["profiles"]}
    proxy = {item["PuzzleId"]: item for item in json.loads(args.proxy_input.read_text(encoding="utf-8"))["profiles"]}
    rows = []
    for puzzle_id, profile in base.items():
        if puzzle_id not in maia or puzzle_id not in proxy:
            continue
        if any(name not in profile["metrics"] for name in BASE_FEATURES):
            continue
        if any(name not in maia[puzzle_id]["metrics"] for name in MAIA_FEATURES):
            continue
        if any(name not in proxy[puzzle_id]["metrics"] for name in PROXY_FEATURES + THREAT_TREE_FEATURES):
            continue
        row = feature_row(profile, maia[puzzle_id])
        row.update({name: float(proxy[puzzle_id]["metrics"][name]) for name in PROXY_FEATURES + THREAT_TREE_FEATURES})
        rows.append((profile, row))
    ratings = np.array([float(profile["Rating"]) for profile, _row in rows])
    groups = [game_group(profile) for profile, _row in rows]
    sets = {
        "forcing_solution_baseline": BASE_FEATURES,
        "candidate_proxy_only": PROXY_FEATURES,
        "baseline_plus_candidate_proxy": BASE_FEATURES + PROXY_FEATURES,
        "baseline_plus_proxy_threat_tree": BASE_FEATURES + PROXY_FEATURES + THREAT_TREE_FEATURES,
        "baseline_plus_maia": BASE_FEATURES + MAIA_FEATURES,
        "baseline_plus_maia_plus_candidate_proxy": BASE_FEATURES + MAIA_FEATURES + PROXY_FEATURES,
        "baseline_plus_maia_proxy_threat_tree": BASE_FEATURES + MAIA_FEATURES + PROXY_FEATURES + THREAT_TREE_FEATURES,
    }
    results = {}
    for name, features in sets.items():
        x = np.array([[row[feature] for feature in features] for _profile, row in rows])
        predictions, _folds = grouped_ridge(x, ratings, np.array(groups), 5, args.ridge)
        results[name] = {"features": list(features), **score(predictions, ratings)}
    output = {"profiles": len(rows), "games": len(set(groups)), "ridge": args.ridge, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")
    for name, result in results.items():
        print(f"{name}: Spearman={result['spearman']} Pearson={result['pearson']} MAE={result['mae']}")
    print(f"Wrote {args.output}.")


if __name__ == "__main__":
    main()
