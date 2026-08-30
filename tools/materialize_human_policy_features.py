"""Materialize resumable full-legal-move features for human S-Chess policy training.

The expensive part of policy experiments is evaluating every legal Seirawan move
with pyffish. This tool stores that work once per sampled human decision. It
writes one complete JSON record per decision, so interruption is safe and
--resume only processes missing decisions from the fixed plan.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from train_schess_human_policy import (
    count_experience,
    player_key,
    reservoir_sample,
    row_features,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/policy/chesscom_human_moves_full.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/policy/human_policy_features_5000.jsonl"))
    parser.add_argument("--plan", type=Path, default=None, help="Fixed decision sample; defaults beside --output.")
    parser.add_argument("--max-decisions", type=int, default=5_000)
    parser.add_argument("--min-ply", type=int, default=4)
    parser.add_argument("--min-elo", type=int, default=0)
    parser.add_argument("--max-legal-moves", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def default_plan(output: Path) -> Path:
    return output.with_name(f"{output.stem}.plan.jsonl")


def read_plan(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_plan(path: Path, records: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "metadata", **metadata}) + "\n")
        for record in records:
            handle.write(json.dumps(record) + "\n")


def existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                result.add(str(value["decision_id"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return result


def decision_id(record: dict[str, Any]) -> str:
    return f"{record.get('game_id')}:{record.get('ply')}"


def materialize(record: dict[str, Any], experience: int, max_legal_moves: int) -> dict[str, Any] | None:
    fen = str(record["fen"])
    played = str(record["move"])
    legal = list(pyffish.legal_moves("seirawan", fen, []))
    if played not in legal or len(legal) < 2 or len(legal) > max_legal_moves:
        return None
    rows: list[dict[str, Any]] = []
    for move in legal:
        features = row_features(fen, move, len(legal), experience)
        rows.append({"move": move, "label": int(move == played), "features": features})
    return {
        "decision_id": decision_id(record),
        "player": player_key(record),
        "game_id": str(record.get("game_id", "")),
        "source_ply": int(record.get("ply", 0)),
        "mover_elo": int(record.get("mover_elo") or 0),
        "legal_move_count": len(legal),
        "rows": rows,
    }


def main() -> None:
    args = parse_args()
    plan = args.plan or default_plan(args.output)
    if plan.exists():
        planned = read_plan(plan)
        metadata = planned.pop(0) if planned and planned[0].get("kind") == "metadata" else {}
        print(f"Loaded fixed plan {plan}: decisions={len(planned):,} metadata={metadata}", flush=True)
    else:
        print("Counting player experience...", flush=True)
        experience = count_experience(args.input, args.min_ply)
        print("Sampling a fixed decision plan...", flush=True)
        planned, eligible = reservoir_sample(args.input, args.max_decisions, args.min_ply, args.min_elo, args.seed)
        metadata = {
            "input": str(args.input),
            "eligible_decisions": eligible,
            "max_decisions": args.max_decisions,
            "min_ply": args.min_ply,
            "min_elo": args.min_elo,
            "seed": args.seed,
        }
        write_plan(plan, planned, metadata)
        print(f"Wrote fixed plan {plan}: decisions={len(planned):,} eligible={eligible:,}", flush=True)

    print("Counting player experience...", flush=True)
    experience = count_experience(args.input, args.min_ply)
    done = existing_ids(args.output) if args.resume else set()
    if args.output.exists() and not args.resume:
        raise SystemExit(f"Output exists: {args.output}. Use --resume or choose another path.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.resume else "w"
    written = 0
    skipped = 0
    failures = 0
    with args.output.open(mode, encoding="utf-8") as handle:
        for index, record in enumerate(planned, start=1):
            key = decision_id(record)
            if key in done:
                skipped += 1
                continue
            try:
                value = materialize(record, experience[player_key(record)], args.max_legal_moves)
                if value is None:
                    failures += 1
                else:
                    handle.write(json.dumps(value) + "\n")
                    handle.flush()
                    written += 1
            except Exception:
                failures += 1
            if index % 25 == 0 or index == len(planned):
                print(
                    f"Materialized {index}/{len(planned)}; written={written} resumed={skipped} skipped_or_failed={failures}",
                    flush=True,
                )
    print(f"Done. output={args.output} written={written} resumed={skipped} skipped_or_failed={failures}", flush=True)


if __name__ == "__main__":
    main()
