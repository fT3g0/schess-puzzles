"""Benchmark exploratory position-complexity signals against Lichess puzzle ratings."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import pyffish
import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from position_complexity import profile_fen
from schess_puzzles.config import load_config
from schess_puzzles.selector import _load_uci_engine

BUCKETS = ((0, 1200, "under_1200"), (1200, 1600, "1200_1599"), (1600, 2000, "1600_1999"), (2000, 2400, "2000_2399"), (2400, 10000, "2400_plus"))
METRICS = ("branching_bits", "forcing_ratio", "best_move_switches", "best_score_swing_cp", "final_near_best_100cp", "structural_load", "instability_load", "ambiguity_load")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(r"E:\Documents\Schach\Database\lichess_db_puzzle.csv.zst"))
    parser.add_argument("--per-bucket", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260714)
    parser.add_argument("--depths", default="4,6,8,10,12")
    parser.add_argument("--multipv", type=int, default=6)
    parser.add_argument("--discordant-limit", type=int, default=10, help="Per direction: puzzles most above/below the rating predicted by the strongest metric.")
    parser.add_argument("--discordant-output", type=Path, default=Path("data/complexity/lichess_rating_discordant.csv"))
    parser.add_argument("--sample-output", type=Path, default=Path("data/complexity/lichess_rating_sample.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_complexity_benchmark.json"))
    return parser.parse_args()


def bucket_for(rating: int) -> str | None:
    for lower, upper, name in BUCKETS:
        if lower <= rating < upper:
            return name
    return None


def stratified_sample(path: Path, per_bucket: int, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    samples: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen: dict[str, int] = defaultdict(int)
    with path.open("rb") as raw, zstandard.ZstdDecompressor().stream_reader(raw) as compressed:
        reader = csv.DictReader(io.TextIOWrapper(compressed, encoding="utf-8", newline=""))
        for row in reader:
            try:
                rating = int(row["Rating"])
                deviation = int(row["RatingDeviation"])
            except (KeyError, ValueError):
                continue
            bucket = bucket_for(rating)
            if bucket is None or deviation > 100:
                continue
            seen[bucket] += 1
            pool = samples[bucket]
            if len(pool) < per_bucket:
                pool.append(row)
            else:
                replace_index = rng.randrange(seen[bucket])
                if replace_index < per_bucket:
                    pool[replace_index] = row
    return [row for _, _, name in BUCKETS for row in samples[name]]


def rank(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for index, _ in ordered[start:end]:
            ranks[index] = average_rank
        start = end
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    x_mean, y_mean = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_scale = math.sqrt(sum((x - x_mean) ** 2 for x in xs))
    y_scale = math.sqrt(sum((y - y_mean) ** 2 for y in ys))
    return round(numerator / (x_scale * y_scale), 3) if x_scale and y_scale else None


def discordant_puzzles(profiles: list[dict], metric: str, correlation: float, limit: int) -> dict:
    values = [float(profile["candidates"][metric]) for profile in profiles]
    ratings = [float(profile["rating"]) for profile in profiles]
    metric_ranks = rank(values)
    rating_ranks = rank(ratings)
    count = len(profiles)
    direction = 1 if correlation >= 0 else -1
    sorted_ratings = sorted(ratings)
    rows = []
    for profile, value, metric_rank, rating_rank in zip(profiles, values, metric_ranks, rating_ranks):
        metric_percentile = (metric_rank - 1) / max(1, count - 1)
        expected_percentile = metric_percentile if direction > 0 else 1 - metric_percentile
        rating_percentile = (rating_rank - 1) / max(1, count - 1)
        predicted_rating = sorted_ratings[round(expected_percentile * (count - 1))]
        rows.append({
            "PuzzleId": profile["label"],
            "Rating": profile["rating"],
            "PredictedRating": round(predicted_rating, 1),
            "Residual": round(profile["rating"] - predicted_rating, 1),
            "RankResidual": round(rating_percentile - expected_percentile, 3),
            "Metric": metric,
            "MetricValue": value,
            "Themes": " ".join(profile.get("themes", [])),
            "GameUrl": profile.get("game_url", ""),
            "InitialFEN": profile.get("initial_fen", ""),
            "PuzzleFEN": profile["fen"],
            "Moves": profile.get("moves", ""),
        })
    return {
        "metric": metric,
        "spearman": correlation,
        "method": "rating-versus-metric percentile residual",
        "harder_than_predicted": sorted(rows, key=lambda row: row["RankResidual"], reverse=True)[:limit],
        "easier_than_predicted": sorted(rows, key=lambda row: row["RankResidual"])[:limit],
    }

def write_discordant_csv(path: Path, data: dict) -> None:
    rows = [*data["harder_than_predicted"], *data["easier_than_predicted"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["PuzzleId", "Rating", "PredictedRating", "Residual", "RankResidual", "Metric", "MetricValue", "Themes", "GameUrl", "InitialFEN", "PuzzleFEN", "Moves"])
        writer.writeheader()
        writer.writerows(rows)

def main() -> None:
    args = parse_args()
    if args.per_bucket < 1:
        raise SystemExit("--per-bucket must be positive")
    depths = sorted({int(value.strip()) for value in args.depths.split(",") if value.strip()})
    sample = stratified_sample(args.input, args.per_bucket, args.seed)
    args.sample_output.parent.mkdir(parents=True, exist_ok=True)
    with args.sample_output.open("w", encoding="utf-8", newline="") as handle:
        fields = ["PuzzleId", "Rating", "RatingDeviation", "Themes", "GameUrl", "FEN", "Moves", "PuzzleFEN"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in sample:
            opponent_move = row["Moves"].split()[0]
            row["PuzzleFEN"] = pyffish.get_fen("chess", row["FEN"], [opponent_move])
            writer.writerow({field: row.get(field, "") for field in fields})

    config = load_config("config.toml")
    engine = _load_uci_engine(config.paths.variant_puzzler / "uci.py", config.engine.path)
    profiles: list[dict] = []
    for row in sample:
        try:
            puzzle_fen = row["PuzzleFEN"]
            profile = profile_fen(row["PuzzleId"], puzzle_fen, "chess", engine, depths, args.multipv)
        except Exception as exc:
            print(f"skip {row.get('PuzzleId', '?')}: {exc}")
            continue
        profile["rating"] = int(row["Rating"])
        profile["rating_deviation"] = int(row["RatingDeviation"])
        profile["themes"] = row.get("Themes", "").split()
        profile["game_url"] = row.get("GameUrl", "")
        profile["initial_fen"] = row.get("FEN", "")
        profile["moves"] = row.get("Moves", "")
        profiles.append(profile)
        print(f"{profile['label']}: rating={profile['rating']} legal={profile['shape']['legal_moves']} structural={profile['candidates']['structural_load']} instability={profile['candidates']['instability_load']}")

    ratings = [float(item["rating"]) for item in profiles]
    correlations = {}
    for metric in METRICS:
        values = [float(item["candidates"][metric]) for item in profiles]
        correlations[metric] = {"pearson": pearson(values, ratings), "spearman": pearson(rank(values), rank(ratings))}
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for profile in profiles:
        by_bucket[bucket_for(profile["rating"]) or "other"].append(profile)
    bucket_means = {
        name: {"count": len(items), "rating": round(sum(item["rating"] for item in items) / len(items), 1), **{metric: round(sum(item["candidates"][metric] for item in items) / len(items), 3) for metric in METRICS}}
        for name, items in by_bucket.items()
    }
    usable = {metric: values for metric, values in correlations.items() if values["spearman"] is not None}
    strongest_metric = max(usable, key=lambda metric: abs(usable[metric]["spearman"])) if usable else ""
    discordant = discordant_puzzles(profiles, strongest_metric, usable[strongest_metric]["spearman"], args.discordant_limit) if strongest_metric else {}
    if discordant:
        write_discordant_csv(args.discordant_output, discordant)
    report = {"source": str(args.input), "sample_seed": args.seed, "per_bucket": args.per_bucket, "depths": depths, "multipv": args.multipv, "profiles": profiles, "correlations": correlations, "bucket_means": bucket_means, "strongest_metric": strongest_metric, "discordant": discordant}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Correlations with Lichess rating (Pearson / Spearman):")
    for metric, values in correlations.items():
        print(f"  {metric}: {values['pearson']} / {values['spearman']}")
    if discordant:
        print(f"Discordant puzzles use {strongest_metric}; wrote {args.discordant_output}.")
    print(f"Wrote {args.sample_output} and {args.output} for {len(profiles)} puzzle(s).")


if __name__ == "__main__":
    main()