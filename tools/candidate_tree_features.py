"""Probe shallow human-relevant candidate trees for Lichess puzzle difficulty.

For each solver node, expand only up to a few forcing-priority competitors:
candidate -> strongest opponent reply -> best solver continuation. The result keeps
the variant tree explicit without attempting an exhaustive engine search.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forcingness_analysis import VALUES, board_from_fen, move_features
from schess_puzzles.config import load_config
from schess_puzzles.selector import SelectionConfig, _load_uci_engine, evaluate_fen


REFUTATION_CP = 150
LIVE_CP = 100
REPLY_NEAR_BEST_CP = 100
CONVERSION_MATERIAL = 3
CONVERSION_EVAL_CP = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=Path("data/complexity/lichess_transition_probe_500.json"),
    )
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--candidates-per-node", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/complexity/lichess_candidate_tree_probe.json"),
    )
    parser.add_argument(
        "--eval-cache-dir",
        type=Path,
        default=Path("data/cache/evals/candidate_tree_probe"),
    )
    return parser.parse_args()


def subset(profiles: list[dict], limit: int) -> list[dict]:
    if not limit or limit >= len(profiles):
        return profiles
    return sorted(profiles, key=lambda profile: hashlib.sha1(profile["PuzzleId"].encode()).hexdigest())[:limit]


def material_balance(fen: str, root_white: bool) -> int:
    return sum(
        (1 if piece.isupper() == root_white else -1) * VALUES.get(piece.upper(), 0)
        for piece in board_from_fen(fen).values()
    )


def normalized_evaluations(fen: str, root_white: bool, engine, config: SelectionConfig) -> list[tuple[str, int]]:
    evaluations = evaluate_fen("chess", fen, engine, config)
    sign = 1 if (fen.split()[1] == "w") == root_white else -1
    return [(item.move, sign * item.score_cp) for item in evaluations]


def forcing_level(fen: str, move: str) -> int:
    board = board_from_fen(fen)
    white = fen.split()[1] == "w"
    return int(move_features(fen, board, move, white)["level"])


def candidate_moves(node: dict, limit: int) -> list[str]:
    dominance = node.get("candidate_dominance", {})
    solution = node["solution_uci"]
    solution_record = dominance.get("solution_candidate", {})
    solution_priority = solution_record.get("priority", -10_000)
    records = dominance.get("top_candidates", [])
    # Higher and equal priority moves are exactly the candidates a human is most
    # likely to inspect before considering quieter alternatives.
    chosen = [
        record["move"]
        for record in records
        if record["move"] != solution and record.get("priority", -10_000) >= solution_priority
    ]
    return chosen[:limit]


def mean(values: list[float | int]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def enrich_profile(profile: dict, engine, config: SelectionConfig, candidates_per_node: int) -> dict:
    moves = profile["Moves"].split()
    profile_values: list[dict] = []

    for node in profile["nodes"]:
        ply = int(node["ply"])
        root = pyffish.get_fen("chess", profile["InitialFEN"], moves[:ply])
        root_white = root.split()[1] == "w"

        reply = moves[ply + 1] if ply + 1 < len(moves) else ""
        continuation = moves[ply + 2] if ply + 2 < len(moves) else ""
        solution_after = pyffish.get_fen("chess", root, [node["solution_uci"]])
        solution_reply = pyffish.get_fen("chess", solution_after, [reply]) if reply else ""
        solution_leaf = pyffish.get_fen("chess", solution_reply, [continuation]) if continuation else solution_reply
        solution_scores = normalized_evaluations(solution_leaf, root_white, engine, config) if solution_leaf else []
        solution_reference = solution_scores[0][1] if solution_scores else 0

        branches: list[dict] = []
        for candidate in candidate_moves(node, candidates_per_node):
            after_candidate = pyffish.get_fen("chess", root, [candidate])
            reply_evaluations = normalized_evaluations(after_candidate, root_white, engine, config)
            if not reply_evaluations:
                continue
            # Fairy-Stockfish orders from the side to move. In root perspective,
            # the opponent's best reply is therefore the smallest value.
            reply_move, reply_score = min(reply_evaluations, key=lambda item: item[1])
            reply_width = sum(score <= reply_score + REPLY_NEAR_BEST_CP for _, score in reply_evaluations)
            after_reply = pyffish.get_fen("chess", after_candidate, [reply_move])
            continuation_evaluations = normalized_evaluations(after_reply, root_white, engine, config)
            continuation_move = continuation_evaluations[0][0] if continuation_evaluations else ""
            continuation_score = continuation_evaluations[0][1] if continuation_evaluations else reply_score
            leaf = pyffish.get_fen("chess", after_reply, [continuation_move]) if continuation_move else after_reply
            material_gain = material_balance(leaf, root_white) - material_balance(root, root_white)
            gap = solution_reference - continuation_score
            branches.append({
                "candidate": candidate,
                "reply": reply_move,
                "continuation": continuation_move,
                "reply_width": reply_width,
                "reply_forcing_level": forcing_level(after_candidate, reply_move),
                "continuation_forcing_level": forcing_level(after_reply, continuation_move) if continuation_move else 0,
                "continuation_score_cp": continuation_score,
                "gap_to_solution_cp": gap,
                "material_gain": material_gain,
                "refuted": gap >= REFUTATION_CP,
                "live": gap <= LIVE_CP,
                "converts": material_gain >= CONVERSION_MATERIAL and continuation_score >= CONVERSION_EVAL_CP,
            })

        metric = {
            "candidate_count": len(branches),
            "refuted_fraction": mean([int(branch["refuted"]) for branch in branches]),
            "live_fraction": mean([int(branch["live"]) for branch in branches]),
            "conversion_fraction": mean([int(branch["converts"]) for branch in branches]),
            "mean_reply_width": mean([branch["reply_width"] for branch in branches]),
            "mean_reply_forcing_level": mean([branch["reply_forcing_level"] for branch in branches]),
            "mean_continuation_forcing_level": mean([branch["continuation_forcing_level"] for branch in branches]),
            "mean_refutation_gap_cp": mean([branch["gap_to_solution_cp"] for branch in branches]),
            "branches": branches,
        }
        node["candidate_tree"] = metric
        profile_values.append(metric)

    profile["metrics"].update({
        "mean_candidate_tree_alternatives": mean([item["candidate_count"] for item in profile_values]),
        "candidate_tree_refuted_fraction": mean([item["refuted_fraction"] for item in profile_values]),
        "candidate_tree_live_fraction": mean([item["live_fraction"] for item in profile_values]),
        "candidate_tree_conversion_fraction": mean([item["conversion_fraction"] for item in profile_values]),
        "mean_candidate_tree_reply_width": mean([item["mean_reply_width"] for item in profile_values]),
        "mean_candidate_tree_reply_forcing": mean([item["mean_reply_forcing_level"] for item in profile_values]),
        "mean_candidate_tree_continuation_forcing": mean([item["mean_continuation_forcing_level"] for item in profile_values]),
        "mean_candidate_tree_refutation_gap_cp": mean([item["mean_refutation_gap_cp"] for item in profile_values]),
    })
    return profile


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = subset(report["profiles"], args.limit)
    source_config = load_config(args.config)
    engine = _load_uci_engine(source_config.paths.variant_puzzler / "uci.py", source_config.engine.path)
    config = SelectionConfig(
        depth=args.depth,
        multipv=3,
        skip_standard_positions=False,
        eval_cache_dir=args.eval_cache_dir,
        eval_context="candidate_tree_probe",
    )
    completed = []
    for index, profile in enumerate(profiles, start=1):
        try:
            completed.append(enrich_profile(profile, engine, config, args.candidates_per_node))
            print(f"[{index}/{len(profiles)}] {profile['PuzzleId']}: rating={profile['Rating']}")
        except Exception as exc:
            print(f"skip {profile['PuzzleId']}: {exc}")
    report["profiles"] = completed
    report["candidate_tree_definition"] = {
        "scope": "up to N alternative candidates of equal or higher forcing priority; candidate -> best opponent reply -> best solver continuation",
        "reply_width": f"MultiPV replies within {REPLY_NEAR_BEST_CP} cp of the strongest defense, in root perspective",
        "refuted": f"candidate branch continuation trails the known solution leaf by at least {REFUTATION_CP} cp",
        "live": f"candidate branch continuation is within {LIVE_CP} cp of the known solution leaf",
        "conversion": f"after the branch continuation material gain >= {CONVERSION_MATERIAL} and root-perspective score >= {CONVERSION_EVAL_CP} cp",
        "engine_depth": args.depth,
        "candidates_per_node": args.candidates_per_node,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(completed)} puzzle(s).")


if __name__ == "__main__":
    main()