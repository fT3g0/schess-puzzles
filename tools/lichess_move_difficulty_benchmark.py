"""Validate move-by-move puzzle difficulty against Lichess puzzle ratings.

This deliberately differs from position-evaluation difficulty: it asks how hard it is
to play the supplied solution one decision at a time, especially when a shallow engine
suggests a tempting but ultimately inferior alternative.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lichess_complexity_benchmark import BUCKETS, pearson, rank, stratified_sample
from position_complexity import profile_fen
from schess_puzzles.config import load_config
from schess_puzzles.selector import _load_uci_engine

METRICS = (
    "solver_nodes",
    "final_solution_match_rate",
    "low_depth_decoys",
    "mean_low_depth_solution_rank",
    "mean_low_depth_near_best",
    "mean_best_move_switches",
    "mean_instability_load",
    "execution_load",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(r"E:\Documents\Schach\Database\lichess_db_puzzle.csv.zst"))
    parser.add_argument("--per-bucket", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260714)
    parser.add_argument("--depths", default="4,6,8,10,12")
    parser.add_argument("--multipv", type=int, default=8)
    parser.add_argument("--max-solver-nodes", type=int, default=0, help="0 analyzes every solver decision in the Lichess line.")
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_move_difficulty.json"))
    parser.add_argument("--review-output", type=Path, default=Path("data/complexity/lichess_move_difficulty_review.csv"))
    return parser.parse_args()


def solution_nodes(initial_fen: str, moves: list[str], maximum: int) -> list[tuple[int, str, str]]:
    nodes = []
    for index in range(1, len(moves), 2):
        if maximum and len(nodes) >= maximum:
            break
        fen = pyffish.get_fen("chess", initial_fen, moves[:index])
        nodes.append((index, fen, moves[index]))
    return nodes


def solution_rank(row: dict, move: str, fallback: int) -> int:
    for index, item in enumerate(row.get("ranked_moves", []), start=1):
        if item.get("uci") == move:
            return index
    return fallback


def action_profile(row: dict[str, str], engine, depths: list[int], multipv: int, maximum: int) -> dict | None:
    moves = row["Moves"].split()
    if len(moves) < 2:
        return None
    per_node = []
    for ply, fen, solution_move in solution_nodes(row["FEN"], moves, maximum):
        profile = profile_fen(f"{row['PuzzleId']}_ply{ply}", fen, "chess", engine, depths, multipv)
        low, final = profile["engine"][0], profile["engine"][-1]
        fallback_rank = multipv + 1
        per_node.append({
            "ply": ply,
            "solution_uci": solution_move,
            "low_depth": low["depth"],
            "final_depth": final["depth"],
            "low_solution_rank": solution_rank(low, solution_move, fallback_rank),
            "final_solution_rank": solution_rank(final, solution_move, fallback_rank),
            "low_best_uci": low["best_uci"],
            "final_best_uci": final["best_uci"],
            "low_near_best_100cp": low["near_best_100cp"],
            "best_move_switches": profile["candidates"]["best_move_switches"],
            "instability_load": profile["candidates"]["instability_load"],
        })
    if not per_node:
        return None
    final_matches = [node for node in per_node if node["final_solution_rank"] == 1]
    decoys = [node for node in final_matches if node["low_best_uci"] != node["solution_uci"]]
    mean = lambda key: round(sum(node[key] for node in per_node) / len(per_node), 3)
    metrics = {
        "solver_nodes": len(per_node),
        "final_solution_match_rate": round(len(final_matches) / len(per_node), 3),
        "low_depth_decoys": len(decoys),
        "mean_low_depth_solution_rank": mean("low_solution_rank"),
        "mean_low_depth_near_best": mean("low_near_best_100cp"),
        "mean_best_move_switches": mean("best_move_switches"),
        "mean_instability_load": mean("instability_load"),
    }
    # The provisional action score weights actual low-depth decoys most heavily.
    metrics["execution_load"] = round(
        metrics["low_depth_decoys"] * 3
        + (metrics["mean_low_depth_solution_rank"] - 1) * 1.5
        + metrics["mean_best_move_switches"]
        + max(0.0, metrics["mean_low_depth_near_best"] - 1) * 0.5,
        3,
    )
    return {"PuzzleId": row["PuzzleId"], "Rating": int(row["Rating"]), "Themes": row.get("Themes", "").split(), "GameUrl": row.get("GameUrl", ""), "InitialFEN": row["FEN"], "Moves": row["Moves"], "nodes": per_node, "metrics": metrics}


def main() -> None:
    args = parse_args()
    depths = sorted({int(value.strip()) for value in args.depths.split(",") if value.strip()})
    sample = stratified_sample(args.input, args.per_bucket, args.seed)
    config = load_config("config.toml")
    engine = _load_uci_engine(config.paths.variant_puzzler / "uci.py", config.engine.path)
    profiles = []
    for index, row in enumerate(sample, start=1):
        try:
            profile = action_profile(row, engine, depths, args.multipv, args.max_solver_nodes)
        except Exception as exc:
            print(f"skip {row.get('PuzzleId', '?')}: {exc}")
            continue
        if profile:
            profiles.append(profile)
            print(f"[{index}/{len(sample)}] {profile['PuzzleId']}: rating={profile['Rating']} nodes={profile['metrics']['solver_nodes']} decoys={profile['metrics']['low_depth_decoys']} load={profile['metrics']['execution_load']}")
    ratings = [float(profile["Rating"]) for profile in profiles]
    correlations = {}
    for metric in METRICS:
        values = [float(profile["metrics"][metric]) for profile in profiles]
        correlations[metric] = {"pearson": pearson(values, ratings), "spearman": pearson(rank(values), rank(ratings))}
    strongest = max(METRICS, key=lambda metric: abs(correlations[metric]["spearman"] or 0))
    report = {"definition": "move-by-move execution difficulty", "depths": depths, "multipv": args.multipv, "profiles": profiles, "correlations": correlations, "strongest_metric": strongest}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with args.review_output.open("w", encoding="utf-8", newline="") as handle:
        fields = ["PuzzleId", "Rating", "Themes", "GameUrl", *METRICS, "InitialFEN", "Moves"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for profile in profiles:
            writer.writerow({"PuzzleId": profile["PuzzleId"], "Rating": profile["Rating"], "Themes": " ".join(profile["Themes"]), "GameUrl": profile["GameUrl"], **profile["metrics"], "InitialFEN": profile["InitialFEN"], "Moves": profile["Moves"]})
    print("Move-by-move correlations (Pearson / Spearman):")
    for metric, result in correlations.items():
        print(f"  {metric}: {result['pearson']} / {result['spearman']}")
    print(f"Strongest provisional metric: {strongest}")
    print(f"Wrote {args.output} and {args.review_output} for {len(profiles)} puzzle(s).")


if __name__ == "__main__":
    main()