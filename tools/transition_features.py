"""Add engine-backed state-transition features to Lichess puzzle profiles.

This probe stays solution-aware: it measures the supplied line's transition from the
solver position through the reply and next solver move. It is a feature experiment,
not an attempt to extend or validate the Lichess solution.
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
from forcingness_analysis import VALUES, attack_map, board_from_fen, move_features
from schess_puzzles.config import load_config
from schess_puzzles.selector import SelectionConfig, _load_uci_engine, evaluate_fen


CONVERSION_MATERIAL_CP = 3
CONVERSION_EVAL_CP = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_visible_budget_500.json")
    )
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--depth", type=int, default=6, help="Low depth used for tempo and transition probes.")
    parser.add_argument("--limit", type=int, default=0, help="0 means every profile; otherwise deterministic subset size.")
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_transition_probe.json"))
    parser.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals/transition_probe"))
    return parser.parse_args()


def deterministic_subset(profiles: list[dict], limit: int) -> list[dict]:
    if not limit or limit >= len(profiles):
        return profiles
    return sorted(
        profiles,
        key=lambda profile: hashlib.sha1(profile["PuzzleId"].encode("utf-8")).hexdigest(),
    )[:limit]


def material_balance(fen: str, root_white: bool) -> int:
    total = 0
    for piece in board_from_fen(fen).values():
        value = VALUES.get(piece.upper(), 0)
        total += value if piece.isupper() == root_white else -value
    return total


def side_in_check(fen: str, white: bool) -> bool:
    board = board_from_fen(fen)
    king = next((square for square, piece in board.items() if piece == ("K" if white else "k")), "")
    return bool(king and king in attack_map(board, not white))


def normalized_score(fen: str, root_white: bool, engine, config: SelectionConfig) -> int | None:
    evaluations = evaluate_fen("chess", fen, engine, config)
    if not evaluations:
        return None
    score = evaluations[0].score_cp
    return score if (fen.split()[1] == "w") == root_white else -score


def tempo_threat(fen: str, root_white: bool, engine, config: SelectionConfig, normal_score: int | None) -> dict:
    """Measure a current threat through a pseudo opponent turn.

    Mate threats and ordinary evaluation loss are separate features. The centipawn
    value is clipped so a mate score cannot dominate every non-mating transition.
    """
    empty = {"delta_cp": None, "mate_threat": False}
    if normal_score is None or side_in_check(fen, root_white):
        return empty
    fields = fen.split()
    fields[1] = "b" if fields[1] == "w" else "w"
    fields[3] = "-"
    pseudo = " ".join(fields)
    if not pyffish.legal_moves("chess", pseudo, []):
        return empty
    opponent_turn_score = normalized_score(pseudo, root_white, engine, config)
    if opponent_turn_score is None:
        return empty
    return {
        "delta_cp": max(-5000, min(5000, normal_score - opponent_turn_score)),
        "mate_threat": abs(opponent_turn_score) >= 90000 and abs(normal_score) < 90000,
    }


def forcing_count(fen: str) -> int:
    board = board_from_fen(fen)
    white = fen.split()[1] == "w"
    return sum(
        move_features(fen, board, move, white)["level"] >= 2
        for move in pyffish.legal_moves("chess", fen, [])
    )


def enrich_profile(profile: dict, engine, config: SelectionConfig) -> dict:
    moves = profile["Moves"].split()
    values = []
    for node in profile["nodes"]:
        ply = int(node["ply"])
        root = pyffish.get_fen("chess", profile["InitialFEN"], moves[:ply])
        root_white = root.split()[1] == "w"
        solution = node["solution_uci"]
        after_solution = pyffish.get_fen("chess", root, [solution])
        reply = moves[ply + 1] if ply + 1 < len(moves) else ""
        after_reply = pyffish.get_fen("chess", after_solution, [reply]) if reply else ""
        continuation = moves[ply + 2] if ply + 2 < len(moves) else ""
        after_continuation = pyffish.get_fen("chess", after_reply, [continuation]) if continuation else ""

        root_score = normalized_score(root, root_white, engine, config)
        solution_score = normalized_score(after_solution, root_white, engine, config)
        reply_score = normalized_score(after_reply, root_white, engine, config) if after_reply else None
        continuation_score = normalized_score(after_continuation, root_white, engine, config) if after_continuation else None
        root_material = material_balance(root, root_white)
        solution_material = material_balance(after_solution, root_white)
        reply_material = material_balance(after_reply, root_white) if after_reply else root_material
        continuation_material = material_balance(after_continuation, root_white) if after_continuation else reply_material
        material_gain = continuation_material - root_material
        eval_gain = (continuation_score - root_score) if root_score is not None and continuation_score is not None else None
        converted = bool(
            after_continuation
            and material_gain >= CONVERSION_MATERIAL_CP
            and continuation_score is not None
            and continuation_score >= CONVERSION_EVAL_CP
        )
        tempo = tempo_threat(root, root_white, engine, config, root_score)
        candidate_dominance = node.get("candidate_dominance", {})
        solution_top_priority = bool(candidate_dominance.get("solution_top_priority", False))
        metric = {
            "root_material_balance": root_material,
            "root_material_deficit": max(0, -root_material),
            "tempo_threat_delta_cp": tempo["delta_cp"],
            "tempo_mate_threat": tempo["mate_threat"],
            "solution_eval_delta_cp": None if root_score is None or solution_score is None else solution_score - root_score,
            "reply_eval_delta_cp": None if solution_score is None or reply_score is None else reply_score - solution_score,
            "continuation_eval_delta_cp": eval_gain,
            "solution_material_delta": solution_material - root_material,
            "reply_material_delta": reply_material - solution_material,
            "continuation_material_delta": material_gain,
            "converted_after_next_solver_move": converted,
            "top_priority_converts": solution_top_priority and converted,
            "post_continuation_forcing_count": forcing_count(after_continuation) if after_continuation else None,
        }
        node["transition"] = metric
        values.append(metric)

    def mean(key: str) -> float:
        usable = [float(value[key]) for value in values if value[key] is not None]
        return round(sum(usable) / len(usable), 3) if usable else 0.0

    profile["metrics"].update({
        "mean_root_material_balance": mean("root_material_balance"),
        "mean_root_material_deficit": mean("root_material_deficit"),
        "mean_tempo_threat_delta_cp": mean("tempo_threat_delta_cp"),
        "tempo_mate_threat_fraction": round(sum(value["tempo_mate_threat"] for value in values) / len(values), 3),
        "mean_solution_eval_delta_cp": mean("solution_eval_delta_cp"),
        "mean_reply_eval_delta_cp": mean("reply_eval_delta_cp"),
        "mean_continuation_eval_delta_cp": mean("continuation_eval_delta_cp"),
        "mean_continuation_material_delta": mean("continuation_material_delta"),
        "conversion_fraction": round(sum(value["converted_after_next_solver_move"] for value in values) / len(values), 3),
        "top_priority_conversion_fraction": round(sum(value["top_priority_converts"] for value in values) / len(values), 3),
        "mean_post_continuation_forcing_count": mean("post_continuation_forcing_count"),
    })
    return profile


def main() -> None:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    profiles = deterministic_subset(report["profiles"], args.limit)
    source_config = load_config(args.config)
    engine = _load_uci_engine(source_config.paths.variant_puzzler / "uci.py", source_config.engine.path)
    config = SelectionConfig(
        depth=args.depth,
        multipv=1,
        skip_standard_positions=False,
        eval_cache_dir=args.eval_cache_dir,
        eval_context="transition_probe",
    )
    completed = []
    for index, profile in enumerate(profiles, start=1):
        try:
            completed.append(enrich_profile(profile, engine, config))
            print(f"[{index}/{len(profiles)}] {profile['PuzzleId']}: rating={profile['Rating']}")
        except Exception as exc:
            print(f"skip {profile['PuzzleId']}: {exc}")
    report["profiles"] = completed
    report["transition_definition"] = {
        "tempo_threat": "root-perspective low-depth evaluation drop after a pseudo turn flip; skipped while in check and en-passant removed; centipawn delta clipped at 5000 and mate kept as a separate flag",
        "conversion": "after the known reply and next solver move, material gain >= 3 and low-depth root-perspective evaluation >= +200 cp",
        "scope": "solution-aware transition probe, intended for feature development before candidate-branch expansion",
        "engine_depth": args.depth,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} for {len(completed)} puzzle(s).")


if __name__ == "__main__":
    main()
