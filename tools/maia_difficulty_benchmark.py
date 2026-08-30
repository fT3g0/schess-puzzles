"""Probe Maia-2 human move probabilities as Lichess puzzle-difficulty signals.

The input is an existing move-difficulty profile.  It contains the initial FEN and
the known Lichess puzzle line, so this script does no engine analysis.  It asks
Maia about every solver decision at several equal player/opponent Elo levels.

This is deliberately a standard-chess calibration experiment.  Maia cannot read
S-Chess board states or gating moves; only the distilled signals may later be
tested as transferable concepts.
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

from lichess_complexity_benchmark import pearson, rank


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/complexity/lichess_move_difficulty_25.json"),
        help="Existing Lichess move-difficulty profile JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/complexity/lichess_maia_probe_25.json"),
    )
    parser.add_argument(
        "--elos",
        default="800,1000,1200,1400,1600,1800,2000,2200,2400",
        help="Comma-separated equal active/opponent Elo levels.",
    )
    parser.add_argument("--model-type", choices=("rapid", "blitz"), default="rapid")
    parser.add_argument("--device", default="cpu", help="Maia device, e.g. cpu or cuda.")
    parser.add_argument("--limit", type=int, default=0, help="0 means all profiles in input.")
    return parser.parse_args()


def solver_positions(initial_fen: str, moves: list[str]) -> list[tuple[int, str, str]]:
    """Return every solver-to-move FEN paired with its expected UCI move."""
    return [
        (ply, pyffish.get_fen("chess", initial_fen, moves[:ply]), moves[ply])
        for ply in range(1, len(moves), 2)
    ]


def entropy(probabilities: dict[str, float]) -> float:
    return -sum(probability * math.log(probability) for probability in probabilities.values() if probability > 0)


def analyze_node(inference, model, prepared, fen: str, solution: str, elos: list[int]) -> dict:
    by_elo: dict[str, dict] = {}
    for elo in elos:
        move_probs, _ = inference.inference_each(model, prepared, fen, elo, elo)
        ranked = sorted(move_probs.items(), key=lambda item: item[1], reverse=True)
        solution_probability = float(move_probs.get(solution, 0.0))
        solution_rank = next((index for index, (move, _) in enumerate(ranked, start=1) if move == solution), len(ranked) + 1)
        top_move, top_probability = ranked[0]
        by_elo[str(elo)] = {
            "solution_probability": round(solution_probability, 8),
            "solution_rank": solution_rank,
            "top1_match": top_move == solution,
            "top1_probability": round(float(top_probability), 8),
            "solution_gap_to_top1": round(float(top_probability) - solution_probability, 8),
            "move_entropy": round(entropy(move_probs), 6),
            "legal_moves": len(ranked),
            "top_move": top_move,
        }
    return by_elo


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def puzzle_metrics(nodes: list[dict], elos: list[int]) -> dict[str, float]:
    metrics: dict[str, float] = {"solver_nodes": len(nodes)}
    for elo in elos:
        key = str(elo)
        data = [node["maia"][key] for node in nodes]
        probabilities = [max(1e-12, float(item["solution_probability"])) for item in data]
        metrics[f"maia_mean_log_probability_{elo}"] = round(mean([math.log(value) for value in probabilities]), 6)
        metrics[f"maia_min_log_probability_{elo}"] = round(min(math.log(value) for value in probabilities), 6)
        metrics[f"maia_mean_solution_rank_{elo}"] = round(mean([float(item["solution_rank"]) for item in data]), 4)
        metrics[f"maia_top1_fraction_{elo}"] = round(mean([float(item["top1_match"]) for item in data]), 4)
        metrics[f"maia_mean_gap_to_top1_{elo}"] = round(mean([float(item["solution_gap_to_top1"]) for item in data]), 6)
        metrics[f"maia_mean_entropy_{elo}"] = round(mean([float(item["move_entropy"]) for item in data]), 6)
    return metrics


def correlations(profiles: list[dict]) -> dict[str, dict[str, float | None]]:
    ratings = [float(profile["Rating"]) for profile in profiles]
    metrics = sorted({metric for profile in profiles for metric in profile["metrics"]})
    result: dict[str, dict[str, float | None]] = {}
    for metric in metrics:
        values = [float(profile["metrics"].get(metric, 0.0)) for profile in profiles]
        result[metric] = {
            "pearson": pearson(values, ratings),
            "spearman": pearson(rank(values), rank(ratings)),
        }
    return result


def main() -> None:
    args = parse_args()
    try:
        from maia2 import inference, model
    except ImportError as exc:  # pragma: no cover - setup error is user-facing.
        raise SystemExit("Maia-2 is not installed. Run: python -m pip install maia2") from exc

    elos = sorted({int(value.strip()) for value in args.elos.split(",") if value.strip()})
    source = json.loads(args.input.read_text(encoding="utf-8"))
    candidates = source["profiles"][: args.limit or None]
    print(f"Loading Maia-2 {args.model_type} on {args.device}; profiles={len(candidates)} elos={elos}")
    maia_model = model.from_pretrained(type=args.model_type, device=args.device)
    prepared = inference.prepare()

    profiles = []
    for index, profile in enumerate(candidates, start=1):
        moves = profile["Moves"].split()
        nodes = []
        try:
            for ply, fen, solution in solver_positions(profile["InitialFEN"], moves):
                nodes.append({
                    "ply": ply,
                    "fen": fen,
                    "solution_uci": solution,
                    "maia": analyze_node(inference, maia_model, prepared, fen, solution, elos),
                })
        except Exception as exc:
            print(f"skip {profile['PuzzleId']}: {exc}")
            continue
        result = {
            "PuzzleId": profile["PuzzleId"],
            "Rating": profile["Rating"],
            "Themes": profile.get("Themes", []),
            "GameUrl": profile.get("GameUrl", ""),
            "InitialFEN": profile["InitialFEN"],
            "Moves": profile["Moves"],
            "nodes": nodes,
            "metrics": puzzle_metrics(nodes, elos),
        }
        profiles.append(result)
        metric = result["metrics"]
        print(
            f"[{index}/{len(candidates)}] {result['PuzzleId']}: rating={result['Rating']} "
            f"p1600={metric.get('maia_mean_log_probability_1600', float('nan')):.3f} "
            f"top1@1600={metric.get('maia_top1_fraction_1600', float('nan')):.2f}"
        )

    report = {
        "definition": "Maia-2 standard-chess move-choice signals for Lichess move-execution difficulty",
        "source": str(args.input),
        "model_type": args.model_type,
        "device": args.device,
        "elos": elos,
        "profiles": profiles,
        "correlations": correlations(profiles),
        "caveat": "Standard chess only; no direct S-Chess inference or transfer claim.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Spearman correlations:")
    for metric, result in sorted(report["correlations"].items(), key=lambda item: abs(item[1]["spearman"] or 0), reverse=True):
        print(f"  {metric}: {result['spearman']}")
    print(f"Wrote {args.output} for {len(profiles)} puzzle(s).")


if __name__ == "__main__":
    main()
