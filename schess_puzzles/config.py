from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib


@dataclass(frozen=True)
class EngineConfig:
    path: Path
    variant: str
    depth: int


@dataclass(frozen=True)
class PathConfig:
    variant_puzzler: Path
    raw_games: Path
    positions: Path
    puzzles: Path


@dataclass(frozen=True)
class PipelineConfig:
    loose_depth: int
    strict_depth: int
    min_rating: int
    max_puzzles: int


@dataclass(frozen=True)
class AppConfig:
    engine: EngineConfig
    paths: PathConfig
    pipeline: PipelineConfig
    raw: dict[str, Any]


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    base = config_path.resolve().parent
    paths = raw["paths"]

    return AppConfig(
        engine=EngineConfig(
            path=Path(raw["engine"]["path"]),
            variant=raw["engine"].get("variant", "seirawan"),
            depth=int(raw["engine"].get("depth", 10)),
        ),
        paths=PathConfig(
            variant_puzzler=_resolve(base, paths["variant_puzzler"]),
            raw_games=_resolve(base, paths["raw_games"]),
            positions=_resolve(base, paths["positions"]),
            puzzles=_resolve(base, paths["puzzles"]),
        ),
        pipeline=PipelineConfig(
            loose_depth=int(raw["pipeline"].get("loose_depth", 8)),
            strict_depth=int(raw["pipeline"].get("strict_depth", 14)),
            min_rating=int(raw["pipeline"].get("min_rating", 0)),
            max_puzzles=int(raw["pipeline"].get("max_puzzles", 1000)),
        ),
        raw=raw,
    )


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()
