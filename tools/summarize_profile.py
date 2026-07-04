from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize selector profiling JSONL files.")
    parser.add_argument("profiles", nargs="+", type=Path)
    parser.add_argument("--slow", type=int, default=12, help="Number of slowest events to show.")
    args = parser.parse_args()

    rows = []
    for path in args.profiles:
        if not path.exists():
            print(f"missing: {path}")
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                row["profile"] = str(path)
                rows.append(row)

    if not rows:
        print("No profile events found.")
        return

    groups = defaultdict(lambda: {"count": 0, "ms": 0.0, "cache_hits": 0})
    for row in rows:
        key = (row.get("event"), row.get("context"), row.get("depth"), row.get("multipv"))
        groups[key]["count"] += 1
        groups[key]["ms"] += float(row.get("elapsed_ms") or 0)
        if row.get("cache_hit"):
            groups[key]["cache_hits"] += 1

    print("By phase:")
    print("event\tcontext\tdepth\tmpv\tcount\tseconds\tavg_ms\tcache_hits")
    for (event, context, depth, multipv), data in sorted(groups.items(), key=lambda item: item[1]["ms"], reverse=True):
        avg = data["ms"] / data["count"] if data["count"] else 0
        print(f"{event}\t{context}\t{depth}\t{multipv}\t{data['count']}\t{data['ms']/1000:.2f}\t{avg:.1f}\t{data['cache_hits']}")

    print(f"\nSlowest {args.slow} events:")
    for row in sorted(rows, key=lambda item: float(item.get("elapsed_ms") or 0), reverse=True)[: args.slow]:
        fen = row.get("fen", "")
        print(
            f"{float(row.get('elapsed_ms') or 0)/1000:.2f}s "
            f"{row.get('event')} {row.get('context')} d{row.get('depth')} mpv{row.get('multipv')} "
            f"cache={row.get('cache_hit', '-')} legal={row.get('legal_count', '-')} "
            f"move={row.get('move_number', '-')} side={row.get('side', '-')} source={row.get('source', '-')} fen={fen[:90]}"
        )


if __name__ == "__main__":
    main()