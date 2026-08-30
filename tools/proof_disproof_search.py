"""Selective proof/disproof search for human tactical attention.

Candidates are not accepted because one leaf looks pleasant. Each candidate carries a
claim that must be proven by a cash-out/terminal certificate or remain open. The
attention budget counts only activated candidates and critical defenses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from attention_tree_search import (
    FAIL_MARGIN,
    cashout,
    candidate_tiers,
    critical_defenses,
    in_check,
    static_score,
    terminal,
    material,
)


PROVEN = "proven"
DISPROVEN = "disproven"
OPEN = "open"
DEFERRED = "deferred"
MAX_DEPTH = 3
MAX_CANDIDATES = 4


@dataclass
class ProofAttention:
    candidate_nodes: int = 0
    defense_nodes: int = 0
    disproofs: int = 0
    backtracks: int = 0
    forced_transitions: int = 0
    certificates: int = 0
    open_frontier_peak: int = 0
    trace: list[str] = field(default_factory=list)

    @property
    def nodes(self) -> int:
        return self.candidate_nodes + self.defense_nodes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_transition_probe_500.json"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--depth", type=int, default=MAX_DEPTH)
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_proof_search_probe.json"))
    return parser.parse_args()


def subset(profiles: list[dict], limit: int) -> list[dict]:
    if not limit or limit >= len(profiles):
        return profiles
    return sorted(profiles, key=lambda item: hashlib.sha1(item["PuzzleId"].encode()).hexdigest())[:limit]


def relevant_candidates(fen: str) -> list[dict]:
    """Return the candidate band a human should compare before accepting a move."""
    tiers = candidate_tiers(fen)
    if not tiers:
        return []
    band = list(tiers[0])
    # Checks and captures are not an absolute hierarchy. If a top checking move has
    # no immediate proof, high-value captures one tier below are genuine rivals.
    if tiers[0][0]["tier"] >= 3 and len(tiers) > 1 and tiers[1][0]["tier"] >= 2:
        band.extend(tiers[1])
    return band[:MAX_CANDIDATES]


def material_certificate(before_fen: str, after_fen: str, candidate: dict, solver_white: bool) -> bool:
    """Prove a visible material gain only if direct counterplay cannot erase it."""
    feature = candidate["feature"]
    if feature["captured_value"] < 3:
        return False
    before_material = material(before_fen, solver_white)
    gain = material(after_fen, solver_white) - before_material
    if gain < 200 or in_check(after_fen, solver_white):
        return False
    board = __import__("attention_tree_search").board_from_fen(after_fen)
    opponent_white = after_fen.split()[1] == "w"
    replies = pyffish.legal_moves("chess", after_fen, [])
    target = candidate["move"][2:4]
    for reply in replies:
        reply_feature = __import__("attention_tree_search").move_features(after_fen, board, reply, opponent_white)
        child = pyffish.get_fen("chess", after_fen, [reply])
        # A direct recapture is acceptable only if the retained gain stays clear.
        if reply[2:4] == target and material(child, solver_white) - before_material < 200:
            return False
        # A forcing countercheck or counter-capture must be calculated, not certified away.
        if reply_feature["level"] >= 3 and reply[2:4] != target:
            return False
    return True

def visible_cashout(before_fen: str, after_fen: str, candidate: dict, solver_white: bool) -> bool:
    return material_certificate(before_fen, after_fen, candidate, solver_white)


def initiative_certificate(fen: str, candidate: dict, solver_white: bool) -> bool:
    """Allow an obvious lone forcing move to defer proof to the next puzzle turn."""
    band = relevant_candidates(fen)
    if len(band) != 1 or candidate["tier"] < 3:
        return False
    after = pyffish.get_fen("chess", fen, [candidate["move"]])
    defenses, forced = critical_defenses(after, solver_white)
    if not forced or not defenses:
        return False
    continuation = pyffish.get_fen("chess", after, [defenses[0]["move"]])
    next_band = relevant_candidates(continuation)
    return bool(next_band and next_band[0]["tier"] >= 2)


def prove_candidate(
    fen: str,
    candidate: dict,
    solver_white: bool,
    baseline: int,
    depth: int,
    attention: ProofAttention,
) -> str:
    attention.candidate_nodes += 1
    move = candidate["move"]
    attention.trace.append(f"candidate d={depth} tier={candidate['tier']} status={candidate['status']} {move}")
    if candidate["status"] == "refuted":
        attention.disproofs += 1
        return DISPROVEN

    after = pyffish.get_fen("chess", fen, [move])
    end = terminal(after, solver_white)
    if end == "mate_win" or visible_cashout(fen, after, candidate, solver_white):
        attention.certificates += 1
        return PROVEN
    if end == "mate_loss":
        attention.disproofs += 1
        return DISPROVEN
    if initiative_certificate(fen, candidate, solver_white):
        attention.trace.append("initiative deferred")
        return DEFERRED
    if depth <= 0:
        return OPEN

    defenses, forced = critical_defenses(after, solver_white)
    if not defenses:
        return OPEN
    statuses = []
    for defense in defenses:
        if forced:
            attention.forced_transitions += 1
            attention.trace.append(f"forced {defense['move']}")
        else:
            attention.defense_nodes += 1
            attention.trace.append(f"defense {defense['move']}")
        child = pyffish.get_fen("chess", after, [defense["move"]])
        statuses.append(prove_position(child, solver_white, baseline, depth - 1, attention))
    if DISPROVEN in statuses:
        attention.disproofs += 1
        return DISPROVEN
    if statuses and all(status == PROVEN for status in statuses):
        return PROVEN
    return OPEN


def prove_position(fen: str, solver_white: bool, baseline: int, depth: int, attention: ProofAttention) -> str:
    end = terminal(fen, solver_white)
    if end == "mate_win":
        attention.certificates += 1
        return PROVEN
    if end == "mate_loss":
        attention.disproofs += 1
        return DISPROVEN
    if cashout(fen, solver_white):
        attention.certificates += 1
        return PROVEN
    if depth <= 0:
        return OPEN

    # A clear material collapse is a disproof unless an immediate check remains.
    if static_score(fen, solver_white) - baseline <= -FAIL_MARGIN:
        candidates = relevant_candidates(fen)
        if not candidates or candidates[0]["tier"] < 3:
            attention.trace.append("material disproof")
            attention.disproofs += 1
            return DISPROVEN

    candidates = relevant_candidates(fen)
    attention.open_frontier_peak = max(attention.open_frontier_peak, len(candidates))
    any_open = False
    for index, candidate in enumerate(candidates):
        status = prove_candidate(fen, candidate, solver_white, baseline, depth, attention)
        if status in {PROVEN, DEFERRED}:
            return status
        if status == OPEN:
            any_open = True
        if index < len(candidates) - 1:
            attention.backtracks += 1
    return OPEN if any_open else DISPROVEN


def profile(profile: dict, depth: int) -> dict:
    moves = profile["Moves"].split()
    decisions = []
    for node in profile["nodes"]:
        ply = int(node["ply"])
        fen = pyffish.get_fen("chess", profile["InitialFEN"], moves[:ply])
        solver_white = fen.split()[1] == "w"
        attention = ProofAttention()
        status = prove_position(fen, solver_white, static_score(fen, solver_white), depth, attention)
        decisions.append({
            "ply": ply,
            "solution_uci": node["solution_uci"],
            "status": status,
            "proof_nodes": attention.nodes,
            "candidate_nodes": attention.candidate_nodes,
            "defense_nodes": attention.defense_nodes,
            "disproofs": attention.disproofs,
            "backtracks": attention.backtracks,
            "forced_transitions": attention.forced_transitions,
            "certificates": attention.certificates,
            "open_frontier_peak": attention.open_frontier_peak,
            "trace": attention.trace,
        })
    totals = {
        key: sum(item[key] for item in decisions)
        for key in ("proof_nodes", "candidate_nodes", "defense_nodes", "disproofs", "backtracks", "forced_transitions", "certificates")
    }
    totals["open_frontier_peak"] = max(item["open_frontier_peak"] for item in decisions)
    totals["unresolved_decisions"] = sum(item["status"] == OPEN for item in decisions)
    profile["proof_search"] = {"decisions": decisions, "metrics": totals}
    profile["metrics"].update(totals)
    return profile


def spearman(values: list[float], ratings: list[float]) -> float:
    order = lambda items: [sorted(range(len(items)), key=lambda index: items[index]).index(index) + 1 for index in range(len(items))]
    left, right = order(values), order(ratings)
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    denominator = math.sqrt(sum((item - mean_left) ** 2 for item in left) * sum((item - mean_right) ** 2 for item in right))
    return round(sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right)) / denominator, 3) if denominator else 0.0


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    completed = []
    for index, item in enumerate(subset(report["profiles"], args.limit), start=1):
        try:
            completed.append(profile(item, args.depth))
            metrics = completed[-1]["metrics"]
            print(f"[{index}] {item['PuzzleId']}: rating={item['Rating']} proof={metrics['proof_nodes']} unresolved={metrics['unresolved_decisions']}")
        except Exception as exc:
            print(f"skip {item['PuzzleId']}: {exc}")
    report["profiles"] = completed
    metrics = ["proof_nodes", "candidate_nodes", "defense_nodes", "disproofs", "backtracks", "open_frontier_peak", "unresolved_decisions"]
    ratings = [float(item["Rating"]) for item in completed]
    report["proof_search_definition"] = {
        "claim": "a candidate is accepted only by terminal/material certificate, or deferred only when it is the lone forcing initiative",
        "open": "locally promising but neither proven nor disproven; open claims force rival candidates to be considered",
        "node": "activated candidate or non-forced critical defense",
        "depth": args.depth,
    }
    report["proof_search_correlations"] = {
        metric: spearman([float(item["metrics"][metric]) for item in completed], ratings)
        for metric in metrics
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Proof-search correlations:", report["proof_search_correlations"])
    print(f"Wrote {args.output} for {len(completed)} puzzle(s).")


if __name__ == "__main__":
    main()