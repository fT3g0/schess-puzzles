"""Extract Maia-like, variant-aware candidate-preference proxy features.

The proxy makes no engine calls. It uses a human-motivated forcing hierarchy,
visible material threat, material context, safety, and resulting-position
simplification. It is calibrated on Lichess first, then can be run unchanged on
Seirawan puzzle records.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schess_puzzles.human_candidates import candidate_summary
from lichess_complexity_benchmark import pearson, rank


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_visible_budget_500.json"))
    parser.add_argument("--variant", default="chess")
    parser.add_argument("--limit", type=int, default=0, help="0 means all profiles.")
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_human_candidate_proxy_500.json"))
    return parser.parse_args()


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def profile_proxy(profile: dict, variant: str) -> dict:
    moves = profile["Moves"].split()
    nodes = []
    for node in profile["nodes"]:
        ply = int(node["ply"])
        fen = pyffish.get_fen(variant, profile["InitialFEN"], moves[:ply])
        summary = candidate_summary(variant, fen, node["solution_uci"])
        nodes.append({"ply": ply, "fen": fen, "solution_uci": node["solution_uci"], "proxy": summary})
    return {
        "PuzzleId": profile["PuzzleId"],
        "Rating": profile.get("Rating"),
        "Themes": profile.get("Themes", []),
        "GameUrl": profile.get("GameUrl", ""),
        "InitialFEN": profile["InitialFEN"],
        "Moves": profile["Moves"],
        "nodes": nodes,
        "metrics": {
            "proxy_mean_log_probability": round(mean([math.log(max(1e-12, float(node["proxy"]["solution_probability"]))) for node in nodes]), 6),
            "proxy_min_log_probability": round(min(math.log(max(1e-12, float(node["proxy"]["solution_probability"]))) for node in nodes), 6),
            "proxy_mean_solution_priority_rank": round(mean([float(node["proxy"]["solution_priority_rank"]) for node in nodes]), 4),
            "proxy_mean_solution_sorted_rank": round(mean([float(node["proxy"]["solution_sorted_rank"]) for node in nodes]), 4),
            "proxy_top_priority_fraction": round(mean([float(node["proxy"]["solution_top_priority"]) for node in nodes]), 4),
            "proxy_mean_gap_to_top1": round(mean([float(node["proxy"]["solution_gap_to_top1"]) for node in nodes]), 6),
            "proxy_mean_entropy": round(mean([float(node["proxy"]["candidate_entropy"]) for node in nodes]), 6),
        },
    }


def correlations(profiles: list[dict]) -> dict[str, dict[str, float | None]]:
    ratings = [float(profile["Rating"]) for profile in profiles]
    keys = sorted({key for profile in profiles for key in profile["metrics"]})
    return {
        key: {
            "pearson": pearson([float(profile["metrics"][key]) for profile in profiles], ratings),
            "spearman": pearson(rank([float(profile["metrics"][key]) for profile in profiles]), rank(ratings)),
        }
        for key in keys
    }


def main() -> None:
    args = parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = []
    candidates = source["profiles"][: args.limit or None]
    for index, profile in enumerate(candidates, start=1):
        try:
            profiles.append(profile_proxy(profile, args.variant))
        except Exception as exc:
            print(f"skip {profile.get('PuzzleId', index)}: {exc}")
    result = {
        "definition": "engine-free human candidate preference proxy; forcing tier first, then visible conversion/safety/simplification",
        "source": str(args.input),
        "variant": args.variant,
        "profiles": profiles,
        "correlations": correlations(profiles) if profiles and profiles[0].get("Rating") is not None else {},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(profiles)} puzzle(s).")
    for key, value in sorted(result["correlations"].items(), key=lambda item: abs(item[1]["spearman"] or 0), reverse=True):
        print(f"  {key}: Spearman={value['spearman']}")


if __name__ == "__main__":
    main()
