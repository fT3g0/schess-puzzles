from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path


HIDDEN_BY_DEFAULT = {"standard-like", "trivial-recapture", "trivial-capture", "check-evasion"}


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tactic_key(record: dict, include_source: bool = False) -> tuple:
    key = (
        record.get("fen"),
        record.get("kind"),
        record.get("best_uci"),
        tuple(record.get("line", [])),
    )
    if include_source:
        return (record.get("source"), *key)
    return key


def visible_count(records: list[dict]) -> int:
    return sum(not (HIDDEN_BY_DEFAULT & set(record.get("flags", []))) for record in records)


def main() -> None:
    puzzles = Path("data/puzzles")
    raw = Path("data/raw")
    chess = read_rows(puzzles / "chesscom_all_report.jsonl")
    self_reports = sorted(
        puzzles.glob("selfplay_batch*_report.jsonl"),
        key=lambda path: int(re.search(r"batch(\d+)", path.name).group(1)),
    )
    self_by_batch = [(path.name, read_rows(path)) for path in self_reports]
    self_rows = [(name, record) for name, rows in self_by_batch for record in rows]
    production = [("chess", record) for record in chess] + [("self", record) for _, record in self_rows]

    print(f"chess_all tactics={len(chess)} visible_default={visible_count(chess)}")
    if self_reports:
        print(f"selfplay reports={len(self_reports)} first={self_reports[0].name} last={self_reports[-1].name}")
    print(f"selfplay tactics={len(self_rows)} visible_default={visible_count([record for _, record in self_rows])}")
    print(
        "production_total "
        f"raw={len(production)} "
        f"visible_default={sum(not (HIDDEN_BY_DEFAULT & set(record.get('flags', []))) for _, record in production)} "
        f"dedupe_strict={len({(source, *tactic_key(record, True)) for source, record in production})} "
        f"dedupe_position={len({tactic_key(record, False) for _, record in production})}"
    )

    print("\nselfplay_by_batch")
    for name, rows in self_by_batch:
        print(f"{name} tactics={len(rows)} visible_default={visible_count(rows)}")

    owners: dict[tuple, list[str]] = collections.defaultdict(list)
    for name, rows in self_by_batch:
        for record in rows:
            owners[tactic_key(record, False)].append(name)
    duplicates = [(key, sorted(set(names))) for key, names in owners.items() if len(set(names)) > 1]
    print(f"\nselfplay_duplicate_tactic_keys_ignore_source={len(duplicates)}")
    for key, names in duplicates[:20]:
        print(f"{names}: fen={key[0]} kind={key[1]} best={key[2]}")

    print("\nselfplay_dir_hashes")
    global_hashes: dict[str, list[str]] = collections.defaultdict(list)
    for directory in sorted(raw.glob("selfplay_batch*")):
        pgns = sorted(directory.glob("*.pgn"))
        hashes = set()
        for path in pgns:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes.add(digest)
            global_hashes[digest].append(str(path))
        print(f"{directory.name} games={len(pgns)} unique_pgn_hashes={len(hashes)}")
    duplicate_games = [paths for paths in global_hashes.values() if len(paths) > 1]
    print(f"\nselfplay_duplicate_pgn_hashes_across_batches={len(duplicate_games)}")
    for paths in duplicate_games[:20]:
        print(paths)


if __name__ == "__main__":
    main()
