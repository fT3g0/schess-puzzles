"""Profile candidate measures of chess-variant position complexity.

This is an exploratory local tool.  It deliberately reports independent signals instead
of pretending that one number already captures human puzzle difficulty.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# Permit python .\\tools\\position_complexity.py from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pyffish

from schess_puzzles.config import load_config
from schess_puzzles.selector import SelectionConfig, _load_uci_engine, evaluate_fen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fen", action="append", default=[], help="FEN to profile; repeatable.")
    parser.add_argument("--fen-file", type=Path, help="One FEN per line, optionally 'label<TAB>FEN'.")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--variant", default="seirawan", help="Fairy-Stockfish UCI variant, e.g. seirawan or chess.")
    parser.add_argument("--depths", default="4,6,8,10,12", help="Comma-separated engine depths.")
    parser.add_argument("--multipv", type=int, default=6)
    parser.add_argument("--output", type=Path, default=Path("data/complexity/position_profiles.json"))
    return parser.parse_args()


def read_positions(args: argparse.Namespace) -> list[tuple[str, str]]:
    positions = [(f"fen_{index:02d}", fen.strip()) for index, fen in enumerate(args.fen, start=1) if fen.strip()]
    if args.fen_file:
        for raw in args.fen_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            label, separator, fen = line.partition("\t")
            positions.append((label.strip() if separator else f"file_{len(positions) + 1:02d}", (fen if separator else label).strip()))
    if not positions:
        raise SystemExit("Provide --fen or --fen-file.")
    return positions


def move_shape(variant: str, fen: str, moves: list[str]) -> dict[str, int]:
    sans = [pyffish.get_san_moves(variant, fen, [move])[-1] for move in moves]
    checks = sum(bool(pyffish.gives_check(variant, fen, [move])) for move in moves)
    captures = sum("x" in san for san in sans)
    promotions = sum("=" in san for san in sans)
    gates = sum(len(move) > 4 and move[-1].lower() in {"e", "h"} and "=" not in san for move, san in zip(moves, sans))
    return {"legal_moves": len(moves), "checks": checks, "captures": captures, "promotions": promotions, "gates": gates}


def engine_profile(variant: str, fen: str, engine, depths: list[int], multipv: int) -> list[dict]:
    rows: list[dict] = []
    for depth in depths:
        evals = evaluate_fen(variant, fen, engine, SelectionConfig(depth=depth, multipv=multipv, skip_standard_positions=False))
        best = evals[0] if evals else None
        second = evals[1] if len(evals) > 1 else None
        rows.append({
            "depth": depth,
            "best_uci": best.move if best else "",
            "best_san": best.san if best else "",
            "best_cp": best.score_cp if best else None,
            "second_uci": second.move if second else "",
            "second_cp": second.score_cp if second else None,
            "gap_cp": best.score_cp - second.score_cp if best and second else None,
            "near_best_100cp": sum(1 for item in evals if best and best.score_cp - item.score_cp <= 100),
            "ranked_moves": [{"uci": item.move, "cp": item.score_cp} for item in evals],
        })
    return rows


def candidate_scores(shape: dict[str, int], rows: list[dict]) -> dict[str, float | int]:
    legal = shape["legal_moves"]
    forcing = shape["checks"] + shape["captures"]
    valid_scores = [row["best_cp"] for row in rows if row["best_cp"] is not None]
    # Mate scores are encoded far outside normal centipawn scale. Keep their presence
    # as a signal, but cap the numeric swing so one mate transition cannot dominate it.
    capped_scores = [max(-1000, min(1000, score)) for score in valid_scores]
    mate_score_seen = any(abs(score) > 10000 for score in valid_scores)
    best_moves = [row["best_uci"] for row in rows if row["best_uci"]]
    switches = sum(before != after for before, after in zip(best_moves, best_moves[1:]))
    score_swing = max(capped_scores) - min(capped_scores) if capped_scores else 0
    final = rows[-1] if rows else {}
    ambiguity = int(final.get("near_best_100cp") or 0)
    return {
        "branching_bits": round(math.log2(max(1, legal)), 2),
        "forcing_ratio": round(forcing / max(1, legal), 3),
        "best_move_switches": switches,
        "best_score_swing_cp": score_swing,
        "mate_score_seen": mate_score_seen,
        "final_near_best_100cp": ambiguity,
        # Exploratory aggregates: structural width, low-depth instability, and ambiguity.
        "structural_load": round(math.log2(max(1, legal)) * (1 + forcing / max(1, legal)), 2),
        "instability_load": round(score_swing / 100 + switches * 1.5, 2),
        "ambiguity_load": ambiguity,
    }


def profile_fen(label: str, fen: str, variant: str, engine, depths: list[int], multipv: int) -> dict:
    fields = fen.split()
    if len(fields) < 6:
        raise ValueError("FEN needs all six fields")
    moves = pyffish.legal_moves(variant, fen, [])
    shape = move_shape(variant, fen, moves)
    rows = engine_profile(variant, fen, engine, depths, multipv)
    return {"label": label, "fen": fen, "shape": shape, "engine": rows, "candidates": candidate_scores(shape, rows)}


def main() -> None:
    args = parse_args()
    depths = sorted({int(value.strip()) for value in args.depths.split(",") if value.strip()})
    if not depths or min(depths) < 1:
        raise SystemExit("--depths must contain positive integers.")
    config = load_config(args.config)
    engine = _load_uci_engine(config.paths.variant_puzzler / "uci.py", config.engine.path)
    profiles: list[dict] = []
    for label, fen in read_positions(args):
        try:
            profile = profile_fen(label, fen, args.variant, engine, depths, args.multipv)
        except Exception as exc:
            print(f"skip {label}: {exc}")
            continue
        profiles.append(profile)
        shape, metrics = profile["shape"], profile["candidates"]
        print(f"{label}: legal={shape['legal_moves']} checks={shape['checks']} captures={shape['captures']} "
              f"switches={metrics['best_move_switches']} swing={metrics['best_score_swing_cp']}cp "
              f"structural={metrics['structural_load']} instability={metrics['instability_load']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"variant": args.variant, "depths": depths, "multipv": args.multipv, "profiles": profiles}, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} with {len(profiles)} profile(s).")


if __name__ == "__main__":
    main()