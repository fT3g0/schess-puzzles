"""Audit outcome-clarity metadata over a generated puzzle report.

This does not run an engine or change puzzle visibility.  It is intended for
reviewing the proposed clarity definition before exposing it to website users.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schess_puzzles.clarity import record_clarity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/puzzles/all_report.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/complexity/clarity_audit.json"))
    parser.add_argument("--examples", type=int, default=12)
    return parser.parse_args()


def label(record: dict) -> str:
    source = str(record.get("source") or "unknown source")
    return f"{source} - move {record.get('move_number') or '?'}"


def compact(record: dict, clarity: dict) -> dict:
    return {
        "label": label(record),
        "best_san": record.get("best_san"),
        "kind": record.get("kind"),
        "best_score_cp": record.get("best_score_cp"),
        "flags": record.get("flags", []),
        "clarity": clarity,
        "fen": record.get("fen"),
        "line": record.get("line", []),
    }


def main() -> None:
    args = parse_args()
    rows = []
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                rows.append((record, record_clarity(record)))

    buckets = Counter(clarity["bucket"] for _, clarity in rows)
    outcomes = Counter(clarity["outcome"] for _, clarity in rows)
    ranked = sorted(rows, key=lambda item: item[1]["score"])
    report = {
        "definition": "Outcome clarity: how visibly a solved line establishes mate, material, repetition, or only an engine-evaluated positional result.",
        "input": str(args.input),
        "count": len(rows),
        "buckets": dict(sorted(buckets.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "lowest_examples": [compact(record, clarity) for record, clarity in ranked[: args.examples]],
        "highest_examples": [compact(record, clarity) for record, clarity in ranked[-args.examples :][::-1]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Clarity audit: puzzles={len(rows)} buckets={dict(sorted(buckets.items()))}")
    print(f"Outcomes: {dict(sorted(outcomes.items()))}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
