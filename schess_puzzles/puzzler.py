from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .schess_pgn import write_epd_from_pgn


@dataclass(frozen=True)
class PuzzlerOutputs:
    positions_epd: Path
    loose_epd: Path
    strict_epd: Path
    puzzles_pgn: Path


class VariantPuzzler:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.root = config.paths.variant_puzzler.resolve()

    def convert_pychess_json(self, source: Path, target: Path) -> None:
        self._run_script(
            "json2epd.py",
            "--input-file",
            source,
            "--variant",
            self.config.engine.variant,
            stdout=target,
        )

    def convert_pgn(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            write_epd_from_pgn(source, handle, self.config.engine.variant)

    def find_puzzles(self, positions: Path, target: Path, depth: int) -> None:
        self._run_script(
            "puzzler.py",
            "--engine",
            str(self.config.engine.path),
            "--variant",
            self.config.engine.variant,
            "-d",
            str(depth),
            positions,
            stdout=target,
        )

    def filter_puzzles(self, source: Path, target: Path) -> None:
        self._run_script("filter.py", source, stdout=target)

    def export_pgn(self, source: Path, target: Path) -> None:
        self._run_script("pgn.py", source, stdout=target)

    def _run_script(self, script_name: str, *args: object, stdout: Path | None = None) -> None:
        script = self.root / script_name
        if not script.exists():
            raise FileNotFoundError(f"Missing chess-variant-puzzler script: {script}")

        command = [sys.executable, str(script), *[self._format_arg(arg) for arg in args]]
        kwargs = {
            "cwd": str(self.root),
            "check": True,
            "text": True,
        }
        if stdout is None:
            subprocess.run(command, **kwargs)
            return

        stdout.parent.mkdir(parents=True, exist_ok=True)
        with stdout.open("w", encoding="utf-8") as handle:
            subprocess.run(command, stdout=handle, **kwargs)

    def _format_arg(self, arg: object) -> str:
        if isinstance(arg, Path):
            return str(arg.resolve())
        return str(arg)
