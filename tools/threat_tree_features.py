"""Derive visible threat/quick-refutation tree features from proxy records."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_human_candidate_proxy_threat_500.json"))
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_human_candidate_proxy_threat_tree_500.json"))
    return parser.parse_args()


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def enrich(profile: dict) -> dict:
    values = []
    for node in profile["nodes"]:
        candidates = node["proxy"].get("candidates", [])
        active_threats = [
            candidate
            for candidate in candidates
            if candidate.get("countercheck_examined")
        ]
        quick_refutations = [
            candidate
            for candidate in active_threats
            if float(candidate.get("countercheck_attack_value", 0)) > 0
        ]
        solution = node["proxy"]["solution"]
        metric = {
            "active_threat_candidates": len(active_threats),
            "quick_refutation_decoys": len(quick_refutations),
            "quick_refutation_value": sum(float(item["countercheck_attack_value"]) for item in quick_refutations),
            "solution_certified_material_threat": bool(
                int(solution.get("forcing_level", 0)) == 1
                and float(solution.get("material_threat_value", 0)) > 0
                and float(solution.get("countercheck_attack_value", 0)) == 0
            ),
        }
        node["threat_tree"] = metric
        values.append(metric)
    profile["metrics"].update({
        "mean_active_threat_candidates": round(mean([float(item["active_threat_candidates"]) for item in values]), 4),
        "mean_quick_refutation_decoys": round(mean([float(item["quick_refutation_decoys"]) for item in values]), 4),
        "mean_quick_refutation_value": round(mean([float(item["quick_refutation_value"]) for item in values]), 4),
        "solution_certified_material_threat_fraction": round(mean([float(item["solution_certified_material_threat"]) for item in values]), 4),
    })
    return profile


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    report["profiles"] = [enrich(profile) for profile in report["profiles"]]
    report["threat_tree_definition"] = {
        "active_threat_candidates": "material-threat candidates in the narrow candidate band inspected for counterchecks",
        "quick_refutation_decoys": "active threats whose countercheck leaves no legal way to save the moved piece",
        "solution_certified_material_threat": "the known solution is an active material threat without a persistent countercheck refutation",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(report['profiles'])} puzzle(s).")


if __name__ == "__main__":
    main()
