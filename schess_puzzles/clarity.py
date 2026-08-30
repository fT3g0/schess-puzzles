"""Outcome clarity for generated S-Chess tactic puzzles.

Clarity is intentionally separate from difficulty. It describes how readily a
solver can verify *what the line achieves* once they see the moves. A forced
mate or a secured material win is clear even when finding it was difficult. A
purely positional improvement or equality save without a visible conversion is
less clear and requires trust in an engine evaluation.

The first version uses only record metadata already stored during generation.
It is deliberately cheap enough to calculate for every web export without any
engine work or full FEN replay.
"""
from __future__ import annotations

from typing import Any


def record_clarity(record: dict[str, Any], line: list[str] | None = None) -> dict[str, Any]:
    """Return deterministic, engine-free outcome-clarity metadata for a record."""
    material = record.get("material") or {}
    swing = _number(material.get("swing_line"))
    best_score = _number(record.get("best_score_cp"))
    flags = {str(flag).lower() for flag in record.get("flags", [])}
    reason = str(record.get("reason") or "").lower()
    san_text = " ".join(
        str(value) for value in (
            record.get("best_san"),
            record.get("line_san"),
            record.get("solution_line_san"),
        ) if value
    )
    has_mate = bool(best_score is not None and best_score >= 90000) or "#" in san_text
    has_repetition = any("repetition" in value or "perpetual" in value for value in [*flags, reason])
    checks = san_text.count("+") + san_text.count("#")
    captures = san_text.count("x")
    stored_plies = len(line if line is not None else record.get("line", []) or [])
    forcing_fraction = min(1.0, (checks + captures) / stored_plies) if stored_plies else 0.0
    kind = str(record.get("kind") or "")

    # The primary conclusion is more important than tactical presentation. The
    # later bonus only distinguishes a visibly forcing route from a quiet one.
    if has_mate:
        outcome, score = "checkmate", 100
    elif swing is not None and swing >= 5:
        outcome, score = "decisive-material-win", 91
    elif swing is not None and swing >= 3:
        outcome, score = "major-material-win", 85
    elif swing is not None and swing >= 1:
        outcome, score = "minor-material-win", 70
    elif kind == "drawing" and has_repetition:
        outcome, score = "forced-repetition", 66
    elif kind == "drawing":
        outcome, score = "defensive-equality", 29
    elif best_score is not None and best_score >= 600:
        outcome, score = "positional-winning-advantage", 36
    else:
        outcome, score = "unclear-advantage", 43

    if outcome in {"decisive-material-win", "major-material-win", "minor-material-win", "forced-repetition"}:
        score += min(4, round(forcing_fraction * 4))
    score = max(0, min(100, int(score)))
    return {
        "score": score,
        "bucket": _bucket(score),
        "outcome": outcome,
        "clear_goal": score >= 70,
        "material_swing_line": swing,
        "line_checks": checks,
        "line_captures": captures,
        "forcing_fraction": round(forcing_fraction, 3),
        "has_mate": has_mate,
        "has_repetition": has_repetition,
    }


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _bucket(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"