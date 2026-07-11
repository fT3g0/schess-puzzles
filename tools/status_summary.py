from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path


HIDDEN_BY_DEFAULT = {"standard-like", "trivial-recapture", "trivial-capture", "trivial-capture-cleanup", "check-evasion", "manual-reject", "failed-reverify"}


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


def numbered_batch_key(path: Path) -> int:
    match = re.search(r"batch(\d+)", path.name)
    return int(match.group(1)) if match else -1


def print_batch_rows(title: str, rows_by_batch: list[tuple[str, list[dict]]], *, limit: int | None = None) -> None:
    rows = rows_by_batch if limit is None else rows_by_batch[-limit:]
    if not rows:
        return
    suffix = "" if limit is None or len(rows_by_batch) <= limit else f" (last {limit})"
    print(f"\n{title}{suffix}")
    for name, rows_for_batch in rows:
        print(f"{name} tactics={len(rows_for_batch)} visible_default={visible_count(rows_for_batch)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="Print every selfplay batch and directory hash.")
    parser.add_argument("--recent", type=int, default=10, help="Number of recent batches to show in compact mode.")
    args = parser.parse_args()

    puzzles = Path("data/puzzles")
    raw = Path("data/raw")
    chess = read_rows(puzzles / "chesscom_all_report.jsonl")
    all_report = read_rows(puzzles / "all_report.jsonl")
    self_reports = sorted(puzzles.glob("selfplay_batch*_report.jsonl"), key=numbered_batch_key)
    self_by_batch = [(path.name, read_rows(path)) for path in self_reports]
    self_rows = [(name, record) for name, rows in self_by_batch for record in rows]
    production = [("chess", record) for record in chess] + [("self", record) for _, record in self_rows]

    print(f"all_report tactics={len(all_report)} visible_default={visible_count(all_report)}")
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

    print_batch_rows("selfplay_by_batch", self_by_batch, limit=None if args.verbose else args.recent)

    owners: dict[tuple, list[str]] = collections.defaultdict(list)
    for name, rows in self_by_batch:
        for record in rows:
            owners[tactic_key(record, False)].append(name)
    duplicates = [(key, sorted(set(names))) for key, names in owners.items() if len(set(names)) > 1]
    print(f"\nselfplay_duplicate_tactic_keys_ignore_source={len(duplicates)}")
    if args.verbose:
        for key, names in duplicates[:20]:
            print(f"{names}: fen={key[0]} kind={key[1]} best={key[2]}")

    global_hashes: dict[str, list[str]] = collections.defaultdict(list)
    selfplay_dirs = sorted(raw.glob("selfplay_batch*"), key=numbered_batch_key)
    dir_summaries = []
    for directory in selfplay_dirs:
        pgns = sorted(directory.glob("*.pgn"))
        hashes = set()
        for path in pgns:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes.add(digest)
            global_hashes[digest].append(str(path))
        dir_summaries.append((directory.name, len(pgns), len(hashes)))

    if args.verbose:
        print("\nselfplay_dir_hashes")
        for name, games, unique_hashes in dir_summaries:
            print(f"{name} games={games} unique_pgn_hashes={unique_hashes}")
    elif dir_summaries:
        total_games = sum(games for _, games, _ in dir_summaries)
        incomplete = [(name, games, unique_hashes) for name, games, unique_hashes in dir_summaries if games != unique_hashes or games == 0]
        print(
            "selfplay_dir_hashes "
            f"dirs={len(dir_summaries)} games={total_games} "
            f"incomplete_or_duplicate_within_dir={len(incomplete)}"
        )

    duplicate_games = [paths for paths in global_hashes.values() if len(paths) > 1]
    print(f"selfplay_duplicate_pgn_hashes_across_batches={len(duplicate_games)}")
    if args.verbose:
        for paths in duplicate_games[:20]:
            print(paths)


if __name__ == "__main__":
    main()
