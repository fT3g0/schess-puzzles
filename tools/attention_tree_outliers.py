"""Write attention-tree outliers for manual review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_attention_probe_30.json"))
    parser.add_argument("--output", type=Path, default=Path("data/complexity/attention_tree_outliers_30.md"))
    parser.add_argument("--per-side", type=int, default=8)
    return parser.parse_args()


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    output = [0.0] * len(values)
    for rank, index in enumerate(order, start=1):
        output[index] = rank
    return output


def fen(profile: dict, ply: int) -> str:
    return pyffish.get_fen("chess", profile["InitialFEN"], profile["Moves"].split()[:ply])


def entry(profile: dict, discrepancy: float) -> list[str]:
    metrics = profile["metrics"]
    lines = [
        f"### {profile['PuzzleId']} | rating {profile['Rating']} | discrepancy {discrepancy:+.1f}",
        f"- Lichess: {profile.get('GameUrl', '')}",
        f"- Attention nodes: {metrics['attention_nodes']} (candidates {metrics['candidate_nodes']}, defenses {metrics['critical_defense_nodes']}, tier descents {metrics['tier_descents']})",
    ]
    for number, decision in enumerate(profile["attention_search"]["decisions"], start=1):
        lines.extend([
            f"- Decision {number}: attention={decision['attention_nodes']}; status={decision['status']}; solution '{decision['solution_uci']}'",
            f"  - FEN: '{fen(profile, int(decision['ply']))}'",
            f"  - Trace: {' -> '.join(decision['trace'])}",
        ])
    return lines


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = report["profiles"]
    expected = ranks([float(profile["Rating"]) for profile in profiles])
    observed = ranks([float(profile["metrics"]["attention_nodes"]) for profile in profiles])
    rows = [(actual - target, profile) for target, actual, profile in zip(expected, observed, profiles)]
    rows.sort(key=lambda item: item[0])
    lines = [
        "# Attention Tree Outliers",
        "",
        "Discrepancy = rank(attention nodes) - rank(Lichess rating).",
        "Negative: model calls the puzzle too easy. Positive: model calls it too hard.",
        "",
        "## Too Easy According To The Model",
        "",
    ]
    for discrepancy, profile in rows[:args.per_side]:
        lines.extend(entry(profile, discrepancy))
        lines.append("")
    lines.extend(["## Too Hard According To The Model", ""])
    for discrepancy, profile in rows[-args.per_side:][::-1]:
        lines.extend(entry(profile, discrepancy))
        lines.append("")
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.output}.")


if __name__ == "__main__":
    main()
