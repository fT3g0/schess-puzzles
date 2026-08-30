"""Run the transferable human-candidate proxy on local S-Chess puzzle records.

The default audit is the curated set: small enough for manual inspection, but
spanning the intended difficulty levels and several Hawk/Elephant positions.
It is research-only and does not alter reports, exports, or website data.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schess_puzzles.human_candidates import candidate_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, default=Path("web/public/puzzles.json"))
    parser.add_argument("--curated", type=Path, default=Path("web/curated-puzzles.js"))
    parser.add_argument("--ids", default="", help="Comma-separated IDs; defaults to every curated puzzle.")
    parser.add_argument("--output", type=Path, default=Path("data/complexity/schess_candidate_proxy_curated.json"))
    return parser.parse_args()


def selected_ids(args: argparse.Namespace) -> list[str]:
    if args.ids.strip():
        return [item.strip().lower() for item in args.ids.split(",") if item.strip()]
    return re.findall(r'"([a-z0-9]+)"', args.curated.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    requested = selected_ids(args)
    records = {record["id"].lower(): record for record in json.loads(args.puzzles.read_text(encoding="utf-8"))["puzzles"]}
    output = []
    missing = []
    for puzzle_id in requested:
        record = records.get(puzzle_id)
        if not record:
            missing.append(puzzle_id)
            continue
        fen = record["fen"]
        nodes = []
        for ply in range(0, len(record["solution"]), 2):
            solution = record["solution"][ply]
            summary = candidate_summary("seirawan", fen, solution)
            nodes.append({"ply": ply, "fen": fen, "solution_uci": solution, "proxy": summary})
            if ply + 1 < len(record["solution"]):
                fen = pyffish.get_fen("seirawan", fen, record["solution"][ply : ply + 2])
        output.append({
            "id": record["id"],
            "level": next((level for level, values in _curated_levels(args.curated).items() if record["id"].lower() in values), "unlisted"),
            "fen": record["fen"],
            "solution": record["solution"],
            "solution_line_san": record.get("solution_line_san", ""),
            "categories": record.get("categories", {}),
            "nodes": nodes,
        })
        start = nodes[0]["proxy"]
        print(f"{record['id']}: rank={start['solution_priority_rank']} p={start['solution_probability']:.3f} top={start['top_candidate']['move']}")
    result = {
        "definition": "S-Chess audit of the engine-free transferable candidate-preference proxy",
        "source": str(args.puzzles),
        "requested": requested,
        "missing": missing,
        "puzzles": output,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(output)} puzzle(s); missing={len(missing)}.")


def _curated_levels(path: Path) -> dict[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    result = {}
    for quoted, bare, values in re.findall(r'(?:"([\w-]+)"|([\w-]+)):\s*\[([^\]]*)\]', text):
        result[quoted or bare] = re.findall(r'"([a-z0-9]+)"', values)
    return result


if __name__ == "__main__":
    main()
