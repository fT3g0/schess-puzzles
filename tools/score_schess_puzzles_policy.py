"""Score S-Chess puzzle solver decisions with the local human-policy model.

The policy model ranks every legal move at each solver decision.  This produces
candidate-prior signals for later difficulty research; it intentionally does not
alter website data or visible puzzle categories.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schess_puzzles.human_candidates import candidate_features
from train_schess_human_policy import CANDIDATE_FEATURES, context_features


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, default=Path("web/public/puzzles.json"))
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("data/policy/human_policy_full_legal_500/human_policy_model.joblib"),
    )
    parser.add_argument("--output", type=Path, default=Path("data/complexity/schess_policy_puzzle_scores.json"))
    parser.add_argument("--ids", default="", help="Comma-separated puzzle IDs; defaults to all puzzles.")
    parser.add_argument("--limit", type=int, default=0, help="Limit selected puzzles; 0 means every selected puzzle.")
    parser.add_argument(
        "--reference-experience",
        type=int,
        default=40,
        help="Fixed completed-decision count used for every puzzle scorer context.",
    )
    return parser.parse_args()


def requested_puzzles(data: dict[str, Any], ids: str, limit: int) -> list[dict[str, Any]]:
    records = list(data["puzzles"])
    if ids.strip():
        requested = {value.strip().lower() for value in ids.split(",") if value.strip()}
        records = [record for record in records if str(record["id"]).lower() in requested]
    if limit:
        records = records[:limit]
    return records


def score_decision(
    model: Any,
    feature_names: list[str],
    fen: str,
    solution: str,
    reference_experience: int,
) -> dict[str, Any]:
    legal = list(pyffish.legal_moves("seirawan", fen, []))
    if solution not in legal:
        raise ValueError(f"stored solution {solution!r} is not legal")
    rows: list[dict[str, Any]] = []
    for move in legal:
        candidate = candidate_features("seirawan", fen, move, len(legal))
        row = context_features(fen, len(legal), reference_experience)
        for name in CANDIDATE_FEATURES:
            row[name] = float(candidate[name])
        rows.append({"move": move, "candidate": candidate, "features": row})
    X = np.array([[float(row["features"][name]) for name in feature_names] for row in rows], dtype=np.float64)
    values = model.predict_proba(X)[:, 1]
    total = float(np.sum(values))
    distribution = values / total if total else np.full(len(values), 1 / len(values))
    ordered = sorted(
        zip(rows, values, distribution, strict=True),
        key=lambda value: (-float(value[1]), str(value[0]["move"])),
    )
    solution_sorted_rank = next(index for index, (row, _, _) in enumerate(ordered, start=1) if row["move"] == solution)
    solution_row, solution_probability, solution_share = next(
        (row, probability, share) for row, probability, share in ordered if row["move"] == solution
    )
    top_row, top_probability, top_share = ordered[0]
    tie_epsilon = 1e-12
    strictly_higher = sum(float(probability) > float(solution_probability) + tie_epsilon for _, probability, _ in ordered)
    tie_size = sum(abs(float(probability) - float(solution_probability)) <= tie_epsilon for _, probability, _ in ordered)
    expected_tied_rank = 1.0 + strictly_higher + (tie_size - 1) / 2.0
    entropy = -sum(float(share) * math.log(float(share)) for _, _, share in ordered if share > 0)
    normalized_entropy = entropy / math.log(len(ordered)) if len(ordered) > 1 else 0.0
    return {
        "solution": solution,
        "legal_move_count": len(legal),
        "solution_policy_probability": round(float(solution_probability), 6),
        "solution_probability_share": round(float(solution_share), 6),
        "solution_rank": round(expected_tied_rank, 4),
        "solution_strict_rank": strictly_higher + 1,
        "solution_sorted_rank": solution_sorted_rank,
        "solution_tie_size": tie_size,
        "solution_normalized_rank": round((expected_tied_rank - 1) / max(1, len(legal) - 1), 6),
        "top_move": str(top_row["move"]),
        "top_policy_probability": round(float(top_probability), 6),
        "top_probability_share": round(float(top_share), 6),
        "solution_gap_to_top": round(float(top_probability - solution_probability), 6),
        "higher_ranked_decoys": strictly_higher,
        "candidate_distribution_entropy": round(normalized_entropy, 6),
        "policy_surprisal_bits": round(-math.log2(max(float(solution_share), 1e-12)), 6),
        "uniform_surprisal_bits": round(math.log2(len(legal)), 6),
        "rank_search_cost_bits": round(math.log2(max(expected_tied_rank, 1.0)), 6),
        "solution_candidate": {
            name: solution_row["candidate"][name]
            for name in ("forcing_level", "check", "captured_value", "material_threat_value", "hanging_cost")
        },
        "top_candidate": {
            "move": str(top_row["move"]),
            **{
                name: top_row["candidate"][name]
                for name in ("forcing_level", "check", "captured_value", "material_threat_value", "hanging_cost")
            },
        },
    }


def score_puzzle(model: Any, feature_names: list[str], record: dict[str, Any], experience: int) -> dict[str, Any]:
    fen = str(record["fen"])
    line = [str(move) for move in record.get("solution", [])]
    decisions: list[dict[str, Any]] = []
    for ply, move in enumerate(line):
        if ply % 2 == 0:
            decisions.append(score_decision(model, feature_names, fen, move, experience))
        fen = pyffish.get_fen("seirawan", fen, [move])
    ranks = [float(item["solution_rank"]) for item in decisions]
    gaps = [float(item["solution_gap_to_top"]) for item in decisions]
    rank_costs = [float(item["rank_search_cost_bits"]) for item in decisions]
    surprises = [float(item["policy_surprisal_bits"]) for item in decisions]
    uniform_surprises = [float(item["uniform_surprisal_bits"]) for item in decisions]
    entropies = [float(item["candidate_distribution_entropy"]) for item in decisions]
    return {
        "id": record["id"],
        "fen": record["fen"],
        "solution": line,
        "categories": record.get("categories", {}),
        "clarity": record.get("clarity", {}),
        "decisions": decisions,
        "aggregate": {
            "solver_decisions": len(decisions),
            "first_solution_rank": ranks[0] if ranks else None,
            "max_solution_rank": round(max(ranks), 4) if ranks else None,
            "mean_solution_rank": round(float(np.mean(ranks)), 4) if ranks else None,
            "max_probability_gap": round(max(gaps, default=0.0), 6),
            "sum_higher_ranked_decoys": sum(int(item["higher_ranked_decoys"]) for item in decisions),
            "sum_rank_search_cost_bits": round(sum(rank_costs), 6),
            "max_rank_search_cost_bits": round(max(rank_costs, default=0.0), 6),
            "sum_policy_surprisal_bits": round(sum(surprises), 6),
            "excess_policy_surprisal_bits": round(sum(surprises) - sum(uniform_surprises), 6),
            "mean_candidate_distribution_entropy": round(float(np.mean(entropies)), 6) if entropies else 0.0,
        },
    }


def main() -> None:
    args = parse_args()
    bundle = joblib.load(args.model)
    model = bundle["model"]
    feature_names = list(bundle["features"])
    data = json.loads(args.puzzles.read_text(encoding="utf-8"))
    selected = requested_puzzles(data, args.ids, args.limit)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, record in enumerate(selected, start=1):
        try:
            results.append(score_puzzle(model, feature_names, record, args.reference_experience))
        except Exception as exc:
            failures.append({"id": str(record.get("id", "")), "error": str(exc)})
        if index % 25 == 0 or index == len(selected):
            print(f"Scored {index}/{len(selected)} puzzles; successful={len(results)} failed={len(failures)}", flush=True)
    result = {
        "definition": "Human-policy candidate-prior signals for S-Chess puzzle solver decisions",
        "model": str(args.model),
        "reference_experience": args.reference_experience,
        "source": str(args.puzzles),
        "scored": len(results),
        "failures": failures,
        "puzzles": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
