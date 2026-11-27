"""Resume-safe high-depth audit of solver moves in old self-play extensions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import pyffish
from schess_puzzles.cli import _enrich_report_record, _web_puzzle_id
from schess_puzzles.config import load_config
from schess_puzzles.selector import SelectionConfig, _load_uci_engine, evaluate_fen


def append_event(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-batch", type=int, default=643)
    parser.add_argument("--depth", type=int, default=17)
    parser.add_argument("--multipv", type=int, default=3)
    parser.add_argument("--max-positions", type=int, default=0, help="Stop after this many new engine checks; zero means unlimited.")
    parser.add_argument("--puzzle-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true", help="Apply proven corrections, preserving original reports in the audit directory.")
    parser.add_argument("--audit-dir", type=Path, default=Path("data/cache/selfplay_extension_audit"))
    args = parser.parse_args()
    if args.depth < 1 or args.multipv < 2 or args.max_positions < 0:
        parser.error("depth must be positive, multipv at least 2, and max-positions nonnegative")
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    journal = args.audit_dir / "checks.jsonl"
    existing = {}
    if journal.exists():
        with journal.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                    existing[item["key"]] = item
                except (ValueError, KeyError):
                    raise SystemExit("Invalid audit journal; preserve it and repair it before resuming.")
    cfg = load_config(Path("config.toml"))
    engine = None
    checks = 0
    corrections = 0
    selected = {x.lower() for x in args.puzzle_id}
    paths = sorted(Path("data/puzzles").glob("selfplay_batch*_report.jsonl"))
    for path in paths:
        match = re.fullmatch(r"selfplay_batch(\d+)_report\.jsonl", path.name)
        if not match or int(match.group(1)) > args.max_batch:
            continue
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        changed = False
        stop = False
        for record in records:
            line = record.get("line") or []
            pid = _web_puzzle_id(record)
            if selected and pid.lower() not in selected:
                continue
            if len(line) < 3 or record.get("kind") not in ("winning", "drawing"):
                continue
            for ply in range(2, len(line), 2):
                fen = pyffish.get_fen("seirawan", record["fen"], line[:ply])
                identity = {"fen": fen, "kind": record["kind"], "depth": args.depth, "multipv": args.multipv, "version": 1}
                key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                result = existing.get(key)
                if result is None:
                    if args.max_positions and checks >= args.max_positions:
                        stop = True
                        break
                    if engine is None:
                        engine = _load_uci_engine(cfg.paths.variant_puzzler / "uci.py", cfg.engine.path)
                    evals = evaluate_fen("seirawan", fen, engine, SelectionConfig(depth=args.depth, multipv=args.multipv, eval_cache_dir=args.audit_dir / "evals"))
                    if len(evals) < 2:
                        raise RuntimeError(f"Incomplete engine result for {pid}, ply {ply}; retry later")
                    threshold = 200 if record["kind"] == "winning" else -80
                    alternatives = [e for e in evals if e.move != line[ply] and e.score_cp >= threshold]
                    result = {"key": key, **identity, "puzzle_id": pid, "report": str(path), "ply": ply, "expected": line[ply], "evals": [{"move": e.move, "san": e.san, "cp": e.score_cp} for e in evals], "alternative_moves": [e.move for e in alternatives]}
                    append_event(journal, result)
                    existing[key] = result
                    checks += 1
                    print(f"checked={checks} puzzle={pid} ply={ply + 1} alternatives={len(alternatives)}", flush=True)
                else:
                    threshold = 200 if record["kind"] == "winning" else -80
                    alternatives = [e for e in result["evals"] if e["move"] != line[ply] and e["cp"] >= threshold]
                if alternatives:
                    print(f"CORRECTION {pid} {path.name}: {len(line)} -> {ply - 1} plies", flush=True)
                    corrections += 1
                    if args.apply:
                        record["id"] = pid
                        record["line"] = line[:ply - 1]
                        for field in ("bonus_mate_line", "bonus_mate_start_fen", "bonus_mate_line_san", "bonus_mate_alternative_first_moves", "bonus_mate_alternatives"):
                            record.pop(field, None)
                        record["extension_audit"] = {"depth": args.depth, "multipv": args.multipv, "original_line": line, "removed_from_ply": ply, "check_key": key}
                        record.update(_enrich_report_record(record))
                        changed = True
                    break
            if stop:
                break
        if changed:
            backup = args.audit_dir / "original_reports" / path.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(path, backup)
            temp = path.with_name(path.name + ".audit.tmp")
            with temp.open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(path)
            print(f"Updated {path}; original preserved at {backup}", flush=True)
        if stop:
            print("Reached --max-positions; rerun the same command to resume.", flush=True)
            break
    print(f"Done: new_checks={checks} candidate_corrections={corrections} apply={args.apply}", flush=True)


if __name__ == "__main__":
    main()
