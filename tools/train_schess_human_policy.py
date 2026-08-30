"""Train an initial human candidate prior from real Seirawan games.

This compact, interpretable baseline learns whether humans chose a legal candidate
over deterministic legal alternatives. Evaluation uses completely unseen players.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import joblib
import pyffish
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schess_puzzles.human_candidates import board_from_fen, candidate_features, material

VARIANT = "seirawan"
CANDIDATE_FEATURES = (
    "forcing_level", "check", "captured_value", "material_threat_value",
    "simplification", "mobility_drop", "hanging_cost", "opponent_reply_count",
    "priority", "attractiveness",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/policy/chesscom_human_moves_full.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/policy/human_policy_baseline"))
    parser.add_argument("--max-decisions", type=int, default=2_000)
    parser.add_argument("--negatives", type=int, default=5)
    parser.add_argument("--min-ply", type=int, default=4)
    parser.add_argument("--min-elo", type=int, default=0, help="Use only moves with a recorded Chess.com variant rating at least this value.")
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--max-legal-moves", type=int, default=80)
    parser.add_argument("--all-legal", action="store_true", help="Train and rank against every legal move.")
    parser.add_argument("--feature-cache", type=Path, default=None, help="Use a materialized full-legal feature cache instead of recomputing pyffish features.")
    return parser.parse_args()


def stream_records(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def player_key(record: dict[str, Any]) -> str:
    username = str(record.get("mover_username") or "").strip().lower()
    return username or f"game:{record.get('game_id', '')}:{record.get('side', '')}"


def count_experience(path: Path, min_ply: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in stream_records(path):
        if int(record.get("ply", 0)) >= min_ply:
            counts[player_key(record)] += 1
    return counts


def reservoir_sample(path: Path, maximum: int, min_ply: int, min_elo: int, seed: int) -> tuple[list[dict[str, Any]], int]:
    randomizer = random.Random(seed)
    sample: list[dict[str, Any]] = []
    eligible = 0
    for record in stream_records(path):
        if int(record.get("ply", 0)) < min_ply:
            continue
        mover_elo = int(record.get("mover_elo") or 0)
        if mover_elo < min_elo:
            continue
        eligible += 1
        if len(sample) < maximum:
            sample.append(record)
            continue
        replacement = randomizer.randrange(eligible)
        if replacement < maximum:
            sample[replacement] = record
    return sample, eligible


def context_features(fen: str, legal_count: int, experience: int) -> dict[str, float]:
    board = board_from_fen(fen)
    mover_white = fen.split()[1] == "w"
    own_material = material(board, mover_white)
    opponent_material = material(board, not mover_white)
    return {
        "own_material": float(own_material),
        "opponent_material": float(opponent_material),
        "material_balance": float(own_material - opponent_material),
        "total_material": float(own_material + opponent_material),
        "legal_move_count": float(legal_count),
        "ply": float(int(fen.rsplit(" ", 1)[-1]) * 2),
        "player_experience_log": math.log1p(experience),
    }


def row_features(fen: str, move: str, legal_count: int, experience: int) -> dict[str, float]:
    candidate = candidate_features(VARIANT, fen, move, legal_count)
    row = context_features(fen, legal_count, experience)
    for name in CANDIDATE_FEATURES:
        row[name] = float(candidate[name])
    return row


def sampled_choices(record: dict[str, Any], negatives: int, randomizer: random.Random, all_legal: bool) -> tuple[list[str], int] | None:
    fen = str(record["fen"])
    played = str(record["move"])
    legal = list(pyffish.legal_moves(VARIANT, fen, []))
    if played not in legal or len(legal) < 2:
        return None
    others = [move for move in legal if move != played]
    if all_legal:
        return [played, *others], len(legal)
    return [played, *randomizer.sample(others, min(negatives, len(others)))], len(legal)


def make_examples(decisions: list[dict[str, Any]], experience: Counter[str], negatives: int, max_legal_moves: int, seed: int, all_legal: bool) -> tuple[list[dict[str, Any]], dict[str, int]]:
    randomizer = random.Random(seed)
    rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    for index, record in enumerate(decisions, start=1):
        try:
            choices = sampled_choices(record, negatives, randomizer, all_legal)
            if not choices:
                counters["skipped_played_not_legal"] += 1
                continue
            moves, legal_count = choices
            if legal_count > max_legal_moves:
                counters["skipped_legal_count"] += 1
                continue
            key = player_key(record)
            decision_id = f"{record.get('game_id')}:{record.get('ply')}"
            for rank, move in enumerate(moves):
                row = row_features(str(record["fen"]), move, legal_count, experience[key])
                row.update({
                    "label": 1 if rank == 0 else 0,
                    "decision_id": decision_id,
                    "player": key,
                    "game_id": str(record.get("game_id", "")),
                    "move": move,
                    "source_ply": int(record.get("ply", 0)),
                    "legal_move_count": legal_count,
                })
                rows.append(row)
            counters["usable_decisions"] += 1
        except Exception:
            counters["feature_failures"] += 1
        if index % 100 == 0:
            print(f"Prepared {index}/{len(decisions)} decisions; usable={counters['usable_decisions']}", flush=True)
    return rows, dict(counters)


def matrix(rows: list[dict[str, Any]], feature_names: list[str]) -> np.ndarray:
    return np.array([[float(row[name]) for name in feature_names] for row in rows], dtype=np.float64)


def evaluate_ranking(rows: list[dict[str, Any]], probabilities: np.ndarray) -> dict[str, Any]:
    by_decision: dict[str, list[tuple[dict[str, Any], float]]] = {}
    for row, probability in zip(rows, probabilities, strict=True):
        by_decision.setdefault(str(row["decision_id"]), []).append((row, float(probability)))

    def summarize(decisions: list[list[tuple[dict[str, Any], float]]]) -> dict[str, float]:
        ranks: list[int] = []
        full_legal_random: list[float] = []
        for alternatives in decisions:
            ordered = sorted(alternatives, key=lambda item: -item[1])
            ranks.append(next(i for i, (row, _) in enumerate(ordered, 1) if row["label"] == 1))
            full_legal_random.append(1.0 / float(alternatives[0][0]["legal_move_count"]))
        return {
            "decisions": float(len(ranks)),
            "top1_accuracy": float(sum(rank == 1 for rank in ranks) / len(ranks)),
            "mean_reciprocal_rank": float(np.mean([1.0 / rank for rank in ranks])),
            "mean_rank": float(np.mean(ranks)),
            "full_legal_random_top1": float(np.mean(full_legal_random)),
        }

    all_decisions = list(by_decision.values())
    opening = [items for items in all_decisions if int(items[0][0]["source_ply"]) < 20]
    later = [items for items in all_decisions if int(items[0][0]["source_ply"]) >= 20]
    return {
        "all": summarize(all_decisions),
        "opening_ply_lt_20": summarize(opening) if opening else None,
        "later_ply_ge_20": summarize(later) if later else None,
    }


def load_feature_cache(path: Path, min_elo: int = 0) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    decisions = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            cached = json.loads(line)
            if int(cached.get("mover_elo") or 0) < min_elo:
                continue
            decisions += 1
            for item in cached["rows"]:
                row = dict(item["features"])
                row.update({
                    "label": int(item["label"]),
                    "decision_id": str(cached["decision_id"]),
                    "player": str(cached["player"]),
                    "game_id": str(cached.get("game_id", "")),
                    "move": str(item["move"]),
                    "source_ply": int(cached.get("source_ply", 0)),
                    "legal_move_count": int(cached["legal_move_count"]),
                })
                rows.append(row)
    return rows, {"cached_decisions": decisions, "usable_decisions": decisions}

def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if not args.input.exists():
        raise SystemExit(f"Input corpus not found: {args.input}")

    if args.feature_cache:
        if not args.feature_cache.exists():
            raise SystemExit(f"Feature cache not found: {args.feature_cache}")
        print(f"Loading materialized feature cache {args.feature_cache}...", flush=True)
        rows, counters = load_feature_cache(args.feature_cache, args.min_elo)
        decisions = [None] * int(counters["cached_decisions"])
        eligible = int(counters["cached_decisions"])
        experience = Counter(str(row["player"]) for row in rows)
    else:
        print("Counting player experience...", flush=True)
        experience = count_experience(args.input, args.min_ply)
        print(f"Players with decisions: {len(experience):,}", flush=True)
        print("Reservoir-sampling decisions...", flush=True)
        decisions, eligible = reservoir_sample(args.input, args.max_decisions, args.min_ply, args.min_elo, args.seed)
        print(f"Eligible decisions: {eligible:,}; sampled: {len(decisions):,}", flush=True)
        print("Extracting variant-aware candidate features...", flush=True)
        rows, counters = make_examples(decisions, experience, args.negatives, args.max_legal_moves, args.seed + 1, args.all_legal)
    if not rows:
        raise SystemExit("No usable training rows were generated.")

    feature_names = [*CANDIDATE_FEATURES, "own_material", "opponent_material", "material_balance", "total_material", "legal_move_count", "ply", "player_experience_log"]
    X = matrix(rows, feature_names)
    y = np.array([int(row["label"]) for row in rows])
    groups = np.array([str(row["player"]) for row in rows])
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=args.seed)
    train_indices, test_indices = next(splitter.split(X, y, groups))
    train_groups, test_groups = set(groups[train_indices]), set(groups[test_indices])
    if train_groups & test_groups:
        raise RuntimeError("Player leakage in holdout split.")

    model = HistGradientBoostingClassifier(learning_rate=0.075, max_leaf_nodes=15, l2_regularization=1.0, max_iter=180, random_state=args.seed)
    positive_weight = float(np.sum(y[train_indices] == 0) / np.sum(y[train_indices] == 1))
    weights = np.where(y[train_indices] == 1, positive_weight, 1.0)
    model.fit(X[train_indices], y[train_indices], sample_weight=weights)
    probabilities = model.predict_proba(X[test_indices])[:, 1]

    effective_all_legal = args.all_legal or args.feature_cache is not None
    metrics = {
        "input": str(args.input),
        "feature_cache": str(args.feature_cache) if args.feature_cache else None,
        "eligible_decisions": eligible,
        "min_mover_elo": args.min_elo,
        "sampled_decisions": len(decisions),
        "rows": len(rows),
        "feature_extraction": counters,
        "players": len(experience),
        "train_players": len(train_groups),
        "test_players": len(test_groups),
        "train_rows": int(len(train_indices)),
        "test_rows": int(len(test_indices)),
        "roc_auc": float(roc_auc_score(y[test_indices], probabilities)),
        "average_precision": float(average_precision_score(y[test_indices], probabilities)),
        "ranking_diagnostics": evaluate_ranking([rows[i] for i in test_indices], probabilities),
        "candidate_set": "all_legal" if effective_all_legal else "sampled",
        "candidate_set_random_top1": None if effective_all_legal else float(1 / (1 + args.negatives)),
        "features": feature_names,
        "notes": [
            "All legal moves are ranked when --all-legal is set; otherwise alternatives are deterministic random legal moves.",
            "The holdout is player-disjoint, so metrics do not reuse a player's own choices.",
            "Player experience is a context feature only; this run does not infer a player's rating.",
        ],
    }
    output = args.output_dir / "baseline_metrics.json"
    output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    model_output = args.output_dir / "human_policy_model.joblib"
    joblib.dump({"model": model, "features": feature_names, "variant": VARIANT}, model_output)
    print(json.dumps(metrics, indent=2), flush=True)
    print(f"Wrote {output} and {model_output}", flush=True)


if __name__ == "__main__":
    main()
