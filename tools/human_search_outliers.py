"""Write human-search difficulty outliers as a compact manual-review report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=Path("data/complexity/lichess_human_search_probe_30.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/complexity/human_search_outliers_30.md"),
    )
    parser.add_argument("--per-side", type=int, default=8)
    return parser.parse_args()


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    output = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        rank = (start + end + 2) / 2
        for position in range(start, end + 1):
            output[order[position]] = rank
        start = end + 1
    return output


def decision_fen(profile: dict, ply: int) -> str:
    return pyffish.get_fen("chess", profile["InitialFEN"], profile["Moves"].split()[:ply])


def render_entry(profile: dict, discrepancy: float) -> list[str]:
    metrics = profile["metrics"]
    decisions = profile["human_search"]["decisions"]
    lines = [
        f"### {profile['PuzzleId']} | rating {profile['Rating']} | discrepancy {discrepancy:+.1f}",
        f"- Lichess: {profile.get('GameUrl', '')}",
        f"- Human nodes: {metrics['human_search_nodes']}; solution match rate: {metrics['human_solution_match_rate']}; mean candidates: {metrics['human_mean_candidates']}",
    ]
    for index, decision in enumerate(decisions, start=1):
        fen = decision_fen(profile, int(decision["ply"]))
        marker = "match" if decision["solution_selected"] else "different"
        lines.extend([
            f"- Decision {index}: {marker}; nodes={decision['nodes']}; candidates={decision['candidate_count']}; cutoff={decision['cutoff']}",
            f"  - FEN: '{fen}'",
            f"  - solution '{decision['solution_uci']}', selected '{decision['selected_uci']}'",
        ])
    return lines


def main() -> None:
    config = args()
    report = json.loads(config.input.read_text(encoding="utf-8"))
    profiles = report["profiles"]
    rating_rank = ranks([float(profile["Rating"]) for profile in profiles])
    node_rank = ranks([float(profile["metrics"]["human_search_nodes"]) for profile in profiles])
    rows = []
    for profile, expected, observed in zip(profiles, rating_rank, node_rank):
        rows.append((observed - expected, profile))
    rows.sort(key=lambda item: item[0])

    lines = [
        "# Human Search Outliers",
        "",
        "Discrepancy = rank(human-search nodes) - rank(Lichess rating).",
        "Negative values: model counted too few nodes for the human rating.",
        "Positive values: model counted too many nodes.",
        "",
        "## Too Easy According To The Model",
        "",
    ]
    for discrepancy, profile in rows[: config.per_side]:
        lines.extend(render_entry(profile, discrepancy))
        lines.append("")
    lines.extend(["## Too Hard According To The Model", ""])
    for discrepancy, profile in rows[-config.per_side :][::-1]:
        lines.extend(render_entry(profile, discrepancy))
        lines.append("")
    config.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {config.output} with {config.per_side * 2} outlier(s).")


if __name__ == "__main__":
    main()