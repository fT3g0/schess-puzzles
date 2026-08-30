"""Build a human-only Seirawan move-policy corpus from Chess.com PGN4 files.

Self-play is intentionally not an input option. Each row represents one actual
human decision before the move was made, with its legal Seirawan FEN and the
chosen UCI move. The output is a local research dataset, not puzzle data.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schess_puzzles.schess_pgn import iter_uci_games, read_headers
from schess_puzzles.sources import is_chesscom_official_seirawan_rules


GAME_ID_RE = re.compile(r"chesscom_(\d+)\.pgn4\.txt$", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--glob", default="chesscom_*.pgn4.txt")
    parser.add_argument("--output", type=Path, default=Path("data/policy/chesscom_human_moves.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/policy/chesscom_human_moves_summary.json"))
    parser.add_argument("--limit-files", type=int, default=0, help="0 means every Chess.com PGN4 file.")
    parser.add_argument("--min-plies", type=int, default=8, help="Skip very short games, but keep all valid human decisions otherwise.")
    parser.add_argument("--resume", action="store_true", help="Append after the last completed raw game in an existing .tmp output.")
    return parser.parse_args()


def integer(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def is_genuine_seirawan(headers: dict[str, str]) -> bool:
    """Recognize Chess.com's official two-player Seirawan PGN4 wrapper."""
    rules = headers.get("RuleVariants", "").lower()
    start_fen4 = headers.get("StartFen4", "").replace(" ", "").lower()
    site = headers.get("Site", "").lower()
    return (
        is_chesscom_official_seirawan_rules(headers.get("RuleVariants", ""))
        and "'wb':true" in start_fen4
        and "/variants/seirawan-chess/" in site
    )


def last_completed_game_id(path: Path) -> str | None:
    """Read the final complete JSONL record without loading a large corpus."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 1_000_000))
        lines = handle.read().splitlines()
    for raw in reversed(lines):
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        value = record.get("game_id")
        if value is not None:
            return str(value)
    return None

def game_id(path: Path) -> str:
    match = GAME_ID_RE.search(path.name)
    return match.group(1) if match else path.stem


def main() -> None:
    args = parse_args()
    files = sorted(args.raw_dir.glob(args.glob))
    if args.limit_files:
        files = files[: args.limit_files]
    if not files:
        raise SystemExit(f"No source files match {args.raw_dir / args.glob}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    totals: Counter[str] = Counter()
    elo_values: list[int] = []
    failures: list[dict[str, str]] = []

    resume_after = last_completed_game_id(temporary) if args.resume else None
    mode = "a" if resume_after is not None else "w"
    if resume_after is not None:
        print(f"Resuming after raw game {resume_after} from {temporary}")

    with temporary.open(mode, encoding="utf-8") as handle:
        for index, path in enumerate(files, start=1):
            if resume_after is not None and game_id(path) <= resume_after:
                continue
            totals["files"] += 1
            try:
                source_headers = read_headers(path)
                if not source_headers or not all(is_genuine_seirawan(item) for item in source_headers):
                    totals["non_seirawan_source_files"] += 1
                    continue
                games = iter_uci_games(path, "seirawan")
            except Exception as exc:
                failures.append({"file": str(path), "error": str(exc)})
                totals["parse_failures"] += 1
                continue
            for game_index, game in enumerate(games):
                if not is_genuine_seirawan(game.headers) or game.variant != "seirawan":
                    totals["non_seirawan_games"] += 1
                    continue
                if len(game.moves) < args.min_plies:
                    totals["short_games"] += 1
                    continue
                headers = game.headers
                white_elo, black_elo = integer(headers.get("WhiteElo")), integer(headers.get("BlackElo"))
                white_username, black_username = headers.get("White", ""), headers.get("Black", "")
                current = game.start_fen
                try:
                    for ply, move in enumerate(game.moves):
                        side = current.split()[1]
                        mover_elo = white_elo if side == "w" else black_elo
                        mover_username = white_username if side == "w" else black_username
                        if mover_elo is not None:
                            elo_values.append(mover_elo)
                        record = {
                            "game_id": game_id(path),
                            "game_index": game_index,
                            "ply": ply,
                            "fen": current,
                            "move": move,
                            "side": side,
                            "mover_elo": mover_elo,
                            "mover_username": mover_username,
                            "white_username": white_username,
                            "black_username": black_username,
                            "white_elo": white_elo,
                            "black_elo": black_elo,
                            "time_control": headers.get("TimeControl", ""),
                            "result": headers.get("Result", ""),
                            "site": headers.get("Site", ""),
                            "date": headers.get("Date", ""),
                        }
                        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                        current = pyffish.get_fen("seirawan", current, [move])
                        totals["positions"] += 1
                    totals["games"] += 1
                except Exception as exc:
                    failures.append({"file": str(path), "game_index": str(game_index), "error": str(exc)})
                    totals["game_failures"] += 1
            if index % 100 == 0 or index == len(files):
                print(f"[{index}/{len(files)}] games={totals['games']} positions={totals['positions']} failures={totals['parse_failures'] + totals['game_failures']}")

    temporary.replace(args.output)
    summary = {
        "definition": "Human Chess.com Seirawan choices only; self-play excluded.",
        "resumed_after_game_id": resume_after,
        "raw_dir": str(args.raw_dir),
        "glob": args.glob,
        "output": str(args.output),
        "totals": dict(totals),
        "elo": {
            "count": len(elo_values),
            "minimum": min(elo_values) if elo_values else None,
            "mean": round(sum(elo_values) / len(elo_values), 1) if elo_values else None,
            "maximum": max(elo_values) if elo_values else None,
        },
        "failures": failures[:200],
        "failure_count": len(failures),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} and {args.summary}.")


if __name__ == "__main__":
    main()
