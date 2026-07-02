from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Puzzle:
    fen: str
    moves: list[str]
    variant: str = "seirawan"
    source: str | None = None
    rating: int | None = None
    tags: list[str] | None = None


def write_jsonl(puzzles: list[Puzzle], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for puzzle in puzzles:
            handle.write(json.dumps(asdict(puzzle), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[Puzzle]:
    puzzles: list[Puzzle] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                puzzles.append(Puzzle(**json.loads(line)))
    return puzzles


def read_epd(path: Path) -> list[Puzzle]:
    puzzles: list[Puzzle] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            puzzles.append(_parse_epd_line(line))
    return puzzles


def _parse_epd_line(line: str) -> Puzzle:
    parts = [part.strip() for part in line.split(";")]
    fen = parts[0]
    annotations = _parse_annotations(parts[1:])
    moves = annotations.get("pv", annotations.get("bm", "")).split(",")
    moves = [move for move in moves if move]

    tags = []
    if "type" in annotations:
        tags.append(annotations["type"])

    return Puzzle(
        fen=fen,
        moves=moves,
        variant=annotations.get("variant", "seirawan"),
        source=annotations.get("site"),
        tags=tags,
    )


def _parse_annotations(parts: list[str]) -> dict[str, str]:
    annotations: dict[str, str] = {}
    for part in parts:
        if not part:
            continue
        key, _, value = part.partition(" ")
        annotations[key] = value.strip()
    return annotations
