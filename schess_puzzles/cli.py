from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

from .config import load_config
from .puzzler import VariantPuzzler
from .selfplay import SelfPlayConfig, generate_selfplay_pgns
from .solver import solve_jsonl
from .store import Puzzle, read_epd, write_jsonl
from .sources import ChessComClient, PychessClient
from .selector import SelectionConfig, evaluate_position, positions_from_pgn, select_tactics
from .schess_pgn import read_headers


def main() -> None:
    parser = argparse.ArgumentParser(prog="schess-puzzles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-config")

    fetch_pychess = subparsers.add_parser("fetch-pychess")
    fetch_pychess.add_argument("game_id")
    fetch_pychess.add_argument("--config", default="config.toml")

    discover_pychess = subparsers.add_parser("discover-pychess")
    discover_pychess.add_argument("url")
    discover_pychess.add_argument("--config", default="config.toml")

    fetch_chesscom = subparsers.add_parser("fetch-chesscom")
    fetch_chesscom.add_argument("username")
    fetch_chesscom.add_argument("year", type=int)
    fetch_chesscom.add_argument("month", type=int)
    fetch_chesscom.add_argument("--config", default="config.toml")

    fetch_chesscom_pgn4 = subparsers.add_parser("fetch-chesscom-pgn4")
    fetch_chesscom_pgn4.add_argument("game_id_or_url")
    fetch_chesscom_pgn4.add_argument("--config", default="config.toml")
    fetch_chesscom_pgn4.add_argument("--cookie")
    fetch_chesscom_pgn4.add_argument("--debug-socket", action="store_true")

    discover_chesscom_variants = subparsers.add_parser("discover-chesscom-variants")
    discover_chesscom_variants.add_argument("url")
    discover_chesscom_variants.add_argument("--config", default="config.toml")

    inspect_chesscom_auth = subparsers.add_parser("inspect-chesscom-auth")
    inspect_chesscom_auth.add_argument("--config", default="config.toml")
    inspect_chesscom_auth.add_argument("--cookie")

    format_cookie = subparsers.add_parser("format-cookie")
    format_cookie.add_argument("input", type=Path)
    format_cookie.add_argument("output", type=Path)

    discover_chesscom_archive = subparsers.add_parser("discover-chesscom-archive")
    discover_chesscom_archive.add_argument("--config", default="config.toml")
    discover_chesscom_archive.add_argument("--cookie")
    discover_chesscom_archive.add_argument("--player-id", type=int)
    discover_chesscom_archive.add_argument("--username")
    discover_chesscom_archive.add_argument("--days", default="0-9999")
    discover_chesscom_archive.add_argument("--game-type", default="")
    discover_chesscom_archive.add_argument("--rating-type", default="")
    discover_chesscom_archive.add_argument("--title", default="seirawan")
    discover_chesscom_archive.add_argument("--start-page", type=int, default=0)
    discover_chesscom_archive.add_argument("--pages", type=int, default=1)
    discover_chesscom_archive.add_argument("--archive-timeout", type=int, default=5)
    discover_chesscom_archive.add_argument("--debug-socket", action="store_true")

    fetch_chesscom_archive = subparsers.add_parser("fetch-chesscom-archive")
    fetch_chesscom_archive.add_argument("--config", default="config.toml")
    fetch_chesscom_archive.add_argument("--access-token-file", type=Path, default=Path("access_token.txt"))
    fetch_chesscom_archive.add_argument("--auth-user-id", type=int)
    fetch_chesscom_archive.add_argument("--cookie")
    fetch_chesscom_archive.add_argument("--player-id", type=int)
    fetch_chesscom_archive.add_argument("--username")
    fetch_chesscom_archive.add_argument("--days", default="0-9999")
    fetch_chesscom_archive.add_argument("--game-type", default="")
    fetch_chesscom_archive.add_argument("--rating-type", default="")
    fetch_chesscom_archive.add_argument("--title", default="seirawan")
    fetch_chesscom_archive.add_argument("--start-page", type=int, default=0)
    fetch_chesscom_archive.add_argument("--pages", type=int, default=1)
    fetch_chesscom_archive.add_argument("--archive-timeout", type=int, default=5)
    fetch_chesscom_archive.add_argument("--delay", type=float, default=1.0)
    fetch_chesscom_archive.add_argument("--archive-block-manifest", type=Path, default=Path("data/cache/chesscom_archive_blocks.jsonl"))
    fetch_chesscom_archive.add_argument("--no-archive-block-skip", action="store_true")
    fetch_chesscom_archive.add_argument("--debug-socket", action="store_true")

    crawl_chesscom = subparsers.add_parser("crawl-chesscom")
    crawl_chesscom.add_argument("--config", default="config.toml")
    crawl_chesscom.add_argument("--cookie")
    crawl_chesscom.add_argument("--player-id", type=int, action="append", default=[])
    crawl_chesscom.add_argument("--username", action="append", default=[])
    crawl_chesscom.add_argument("--days", default="0-9999")
    crawl_chesscom.add_argument("--game-type", default="")
    crawl_chesscom.add_argument("--rating-type", default="")
    crawl_chesscom.add_argument("--title", default="seirawan")
    crawl_chesscom.add_argument("--start-page", type=int, default=0)
    crawl_chesscom.add_argument("--pages", type=int, default=1)
    crawl_chesscom.add_argument("--archive-timeout", type=int, default=5)
    crawl_chesscom.add_argument("--max-players", type=int, default=10)
    crawl_chesscom.add_argument("--max-games", type=int, default=100)
    crawl_chesscom.add_argument("--delay", type=float, default=1.0)
    crawl_chesscom.add_argument("--debug-socket", action="store_true")

    chesscom_next = subparsers.add_parser("chesscom-next-tactics")
    chesscom_next.add_argument("games", type=int)
    chesscom_next.add_argument("--config", default="config.toml")
    chesscom_next.add_argument("--access-token-file", type=Path, default=Path("access_token.txt"))
    chesscom_next.add_argument("--auth-user-id", type=int)
    chesscom_next.add_argument("--cookie")
    chesscom_next.add_argument("--player-id", type=int)
    chesscom_next.add_argument("--username")
    chesscom_next.add_argument("--days", default="0-9999")
    chesscom_next.add_argument("--game-type", default="")
    chesscom_next.add_argument("--rating-type", default="")
    chesscom_next.add_argument("--title", default="seirawan")
    chesscom_next.add_argument("--start-page", type=int, default=0)
    chesscom_next.add_argument("--pages", type=int, default=50)
    chesscom_next.add_argument("--archive-timeout", type=int, default=5)
    chesscom_next.add_argument("--delay", type=float, default=1.0)
    chesscom_next.add_argument("--batch-name")
    chesscom_next.add_argument("--depth", type=int, default=10)
    chesscom_next.add_argument("--multipv", type=int, default=6)
    chesscom_next.add_argument("--confirm-depth", type=int, default=20)
    chesscom_next.add_argument("--confirm-multipv", type=int, default=3)
    chesscom_next.add_argument("--confirm-fast-depth", type=int, default=17)
    chesscom_next.add_argument("--confirm-clear-gap-cp", type=int, default=300)
    chesscom_next.add_argument("--confirm-clear-margin-cp", type=int, default=300)
    chesscom_next.add_argument("--confirm-borderline-depth", type=int)
    chesscom_next.add_argument("--confirm-borderline-win-cp", type=int)
    chesscom_next.add_argument("--confirm-borderline-gap-cp", type=int)
    chesscom_next.add_argument("--rescreen-depth", type=int)
    chesscom_next.add_argument("--rescreen-multipv", type=int)
    chesscom_next.add_argument("--rescreen-min-gap-cp", type=int, default=80)
    chesscom_next.add_argument("--rescreen-margin-cp", type=int, default=120)
    chesscom_next.add_argument("--max-plies", type=int, default=7)
    chesscom_next.add_argument("--extension-beam-width", type=int, default=2)
    chesscom_next.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals"))
    chesscom_next.add_argument("--no-update-public", action="store_true")
    chesscom_next.add_argument("--profile-jsonl", type=Path)
    chesscom_next.add_argument("--debug-socket", action="store_true")
    inspect_sources = subparsers.add_parser("inspect-sources")
    inspect_sources.add_argument("files", nargs="+", type=Path)

    pipeline = subparsers.add_parser("pipeline")
    pipeline.add_argument("--config", default="config.toml")
    pipeline.add_argument("--input", type=Path)

    solve = subparsers.add_parser("solve")
    solve.add_argument("puzzles", type=Path)

    list_positions = subparsers.add_parser("list-positions")
    list_positions.add_argument("input", type=Path)
    list_positions.add_argument("--config", default="config.toml")

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("input", type=Path)
    inspect.add_argument("--config", default="config.toml")
    inspect.add_argument("--move-number", type=int)
    inspect.add_argument("--side", choices=["w", "b"])
    inspect.add_argument("--fen")
    inspect.add_argument("--depth", type=int, default=12)
    inspect.add_argument("--multipv", type=int, default=8)
    inspect.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals"))

    select = subparsers.add_parser("select")
    select.add_argument("input", type=Path)
    select.add_argument("--config", default="config.toml")
    select.add_argument("--depth", type=int, default=12)
    select.add_argument("--multipv", type=int, default=8)
    select.add_argument("--confirm-depth", type=int)
    select.add_argument("--confirm-multipv", type=int)
    select.add_argument("--confirm-fast-depth", type=int)
    select.add_argument("--confirm-clear-gap-cp", type=int, default=300)
    select.add_argument("--confirm-clear-margin-cp", type=int, default=300)
    select.add_argument("--confirm-borderline-depth", type=int)
    select.add_argument("--confirm-borderline-win-cp", type=int)
    select.add_argument("--confirm-borderline-gap-cp", type=int)
    select.add_argument("--rescreen-depth", type=int)
    select.add_argument("--rescreen-multipv", type=int)
    select.add_argument("--rescreen-min-gap-cp", type=int, default=80)
    select.add_argument("--rescreen-margin-cp", type=int, default=120)
    select.add_argument("--win-cp", type=int, default=200)
    select.add_argument("--draw-floor-cp", type=int, default=-80)
    select.add_argument("--losing-cp", type=int, default=-150)
    select.add_argument("--min-gap-cp", type=int, default=150)
    select.add_argument("--exclude-recaptures", action="store_true")
    select.add_argument("--extend-critical", action="store_true")
    select.add_argument("--max-plies", type=int, default=7)
    select.add_argument("--extension-beam-width", type=int, default=1)
    select.add_argument("--allow-check-reply-first", action="store_true")
    select.add_argument("--include-standard-positions", action="store_true")
    select.add_argument("--output-jsonl", type=Path)
    select.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals"))

    select_batch = subparsers.add_parser("select-batch")
    select_batch.add_argument("files", nargs="*", type=Path)
    select_batch.add_argument("--config", default="config.toml")
    select_batch.add_argument("--glob", default="data/raw/chesscom_*.pgn4.txt")
    select_batch.add_argument("--start-index", type=int, default=0)
    select_batch.add_argument("--limit", type=int, default=20)
    select_batch.add_argument("--depth", type=int, default=10)
    select_batch.add_argument("--multipv", type=int, default=6)
    select_batch.add_argument("--confirm-depth", type=int)
    select_batch.add_argument("--confirm-multipv", type=int)
    select_batch.add_argument("--confirm-fast-depth", type=int)
    select_batch.add_argument("--confirm-clear-gap-cp", type=int, default=300)
    select_batch.add_argument("--confirm-clear-margin-cp", type=int, default=300)
    select_batch.add_argument("--confirm-borderline-depth", type=int)
    select_batch.add_argument("--confirm-borderline-win-cp", type=int)
    select_batch.add_argument("--confirm-borderline-gap-cp", type=int)
    select_batch.add_argument("--rescreen-depth", type=int)
    select_batch.add_argument("--rescreen-multipv", type=int)
    select_batch.add_argument("--rescreen-min-gap-cp", type=int, default=80)
    select_batch.add_argument("--rescreen-margin-cp", type=int, default=120)
    select_batch.add_argument("--win-cp", type=int, default=200)
    select_batch.add_argument("--draw-floor-cp", type=int, default=-80)
    select_batch.add_argument("--losing-cp", type=int, default=-150)
    select_batch.add_argument("--min-gap-cp", type=int, default=150)
    select_batch.add_argument("--exclude-recaptures", action="store_true")
    select_batch.add_argument("--extend-critical", action="store_true")
    select_batch.add_argument("--max-plies", type=int, default=7)
    select_batch.add_argument("--extension-beam-width", type=int, default=2)
    select_batch.add_argument("--allow-check-reply-first", action="store_true")
    select_batch.add_argument("--include-standard-positions", action="store_true")
    select_batch.add_argument("--output-jsonl", type=Path, default=Path("data/puzzles/chesscom_batch20.jsonl"))
    select_batch.add_argument("--report-jsonl", type=Path, default=Path("data/puzzles/chesscom_batch20_report.jsonl"))
    select_batch.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals"))
    select_batch.add_argument("--profile-jsonl", type=Path)


    suggest_fen = subparsers.add_parser("suggest-fen")
    suggest_fen.add_argument("fen")
    suggest_fen.add_argument("--config", default="config.toml")
    suggest_fen.add_argument("--depth", type=int, default=20)
    suggest_fen.add_argument("--multipv", type=int, default=8)
    suggest_fen.add_argument("--extend-depth", type=int, default=12)
    suggest_fen.add_argument("--extend-multipv", type=int)
    suggest_fen.add_argument("--win-cp", type=int, default=200)
    suggest_fen.add_argument("--draw-floor-cp", type=int, default=-80)
    suggest_fen.add_argument("--losing-cp", type=int, default=-150)
    suggest_fen.add_argument("--min-gap-cp", type=int, default=150)
    suggest_fen.add_argument("--max-plies", type=int, default=7)
    suggest_fen.add_argument("--extension-beam-width", type=int, default=2)
    suggest_fen.add_argument("--allow-check-reply-first", action="store_true")
    suggest_fen.add_argument("--include-standard-positions", action="store_true")
    suggest_fen.add_argument("--source", default="suggested")
    suggest_fen.add_argument("--output-jsonl", type=Path, default=Path("data/puzzles/suggested.jsonl"))
    suggest_fen.add_argument("--report-jsonl", type=Path, default=Path("data/puzzles/suggested_report.jsonl"))
    suggest_fen.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals"))
    suggest_fen.add_argument("--profile-jsonl", type=Path)

    mutate_candidate = subparsers.add_parser("mutate-candidate")
    mutate_candidate.add_argument("inputs", nargs="+", help="FEN strings or text files containing one FEN per line")
    mutate_candidate.add_argument("--config", default="config.toml")
    mutate_candidate.add_argument("--pieces", default="n,N,b,B,r,R,q,Q,h,H,e,E")
    mutate_candidate.add_argument("--depth", type=int, default=20)
    mutate_candidate.add_argument("--multipv", type=int, default=8)
    mutate_candidate.add_argument("--extend-depth", type=int, default=12)
    mutate_candidate.add_argument("--extend-multipv", type=int)
    mutate_candidate.add_argument("--win-cp", type=int, default=200)
    mutate_candidate.add_argument("--draw-floor-cp", type=int, default=-80)
    mutate_candidate.add_argument("--losing-cp", type=int, default=-150)
    mutate_candidate.add_argument("--min-gap-cp", type=int, default=150)
    mutate_candidate.add_argument("--max-plies", type=int, default=7)
    mutate_candidate.add_argument("--extension-beam-width", type=int, default=2)
    mutate_candidate.add_argument("--max-tested-per-fen", type=int, default=200)
    mutate_candidate.add_argument("--min-line-plies", type=int, default=1)
    mutate_candidate.add_argument("--allow-check-reply-first", action="store_true")
    mutate_candidate.add_argument("--include-standard-positions", action="store_true")
    mutate_candidate.add_argument("--source-prefix", default="synthetic_mutation")
    mutate_candidate.add_argument("--output-jsonl", type=Path, default=Path("data/puzzles/mutation_lab.jsonl"))
    mutate_candidate.add_argument("--report-jsonl", type=Path, default=Path("data/puzzles/mutation_lab_report.jsonl"))
    mutate_candidate.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals/mutation_lab"))
    mutate_candidate.add_argument("--profile-jsonl", type=Path)

    retrograde_predecessors = subparsers.add_parser("retrograde-predecessors")
    retrograde_predecessors.add_argument("fen")
    retrograde_predecessors.add_argument("--config", default="config.toml")
    retrograde_predecessors.add_argument("--captures", action="store_true")
    retrograde_predecessors.add_argument("--capture-pieces", default="p,n,b,r,q,h,e")
    retrograde_predecessors.add_argument("--san-regex")
    retrograde_predecessors.add_argument("--max-results", type=int, default=100)
    retrograde_predecessors.add_argument("--output", type=Path, default=Path("data/puzzles/candidate_checks/retrograde_predecessors.jsonl"))

    retrograde_chain = subparsers.add_parser("retrograde-chain")
    retrograde_chain.add_argument("fen")
    retrograde_chain.add_argument("--config", default="config.toml")
    retrograde_chain.add_argument("--steps", type=int, default=2)
    retrograde_chain.add_argument("--captures", action="store_true")
    retrograde_chain.add_argument("--capture-pieces", action="append", default=[])
    retrograde_chain.add_argument("--san-regex", action="append", default=[])
    retrograde_chain.add_argument("--beam-width", type=int, default=20)
    retrograde_chain.add_argument("--max-results-per-node", type=int, default=80)
    retrograde_chain.add_argument("--evaluate", action="store_true")
    retrograde_chain.add_argument("--allow-other-first-move", action="store_true")
    retrograde_chain.add_argument("--depth", type=int, default=20)
    retrograde_chain.add_argument("--multipv", type=int, default=8)
    retrograde_chain.add_argument("--extend-depth", type=int, default=12)
    retrograde_chain.add_argument("--extend-multipv", type=int)
    retrograde_chain.add_argument("--win-cp", type=int, default=200)
    retrograde_chain.add_argument("--draw-floor-cp", type=int, default=-80)
    retrograde_chain.add_argument("--losing-cp", type=int, default=-150)
    retrograde_chain.add_argument("--min-gap-cp", type=int, default=150)
    retrograde_chain.add_argument("--max-plies", type=int, default=9)
    retrograde_chain.add_argument("--extension-beam-width", type=int, default=2)
    retrograde_chain.add_argument("--min-line-plies", type=int, default=1)
    retrograde_chain.add_argument("--allow-check-reply-first", action="store_true")
    retrograde_chain.add_argument("--include-standard-positions", action="store_true")
    retrograde_chain.add_argument("--source-prefix", default="synthetic_retrograde")
    retrograde_chain.add_argument("--output", type=Path, default=Path("data/puzzles/candidate_checks/retrograde_chain.jsonl"))
    retrograde_chain.add_argument("--output-jsonl", type=Path, default=Path("data/puzzles/retrograde_lab.jsonl"))
    retrograde_chain.add_argument("--report-jsonl", type=Path, default=Path("data/puzzles/retrograde_lab_report.jsonl"))
    retrograde_chain.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals/retrograde_lab"))
    retrograde_chain.add_argument("--profile-jsonl", type=Path)
    export_web = subparsers.add_parser("export-web")
    export_web.add_argument("report_jsonl", type=Path, nargs="?", default=Path("data/puzzles/all_report.jsonl"))
    export_web.add_argument("output_json", type=Path, nargs="?", default=Path("web/public/puzzles.json"))
    enrich_mate_lines = subparsers.add_parser("enrich-mate-lines")
    enrich_mate_lines.add_argument("input_report", type=Path)
    enrich_mate_lines.add_argument("output_report", type=Path, nargs="?")
    enrich_mate_lines.add_argument("--config", default="config.toml")
    enrich_mate_lines.add_argument("--depth", type=int, default=20)
    enrich_mate_lines.add_argument("--multipv", type=int, default=5)
    enrich_mate_lines.add_argument("--max-records", type=int, default=0)
    enrich_mate_lines.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals/mate_lines"))
    review_html = subparsers.add_parser("review-html")
    review_html.add_argument("report_jsonl", type=Path)
    review_html.add_argument("output_html", type=Path, nargs="?", default=Path("data/puzzles/review.html"))

    refresh_report_flags = subparsers.add_parser("refresh-report-flags")
    refresh_report_flags.add_argument("input_report", type=Path)
    refresh_report_flags.add_argument("output_report", type=Path, nargs="?")


    reverify_report = subparsers.add_parser("reverify-report")
    reverify_report.add_argument("input_report", type=Path)
    reverify_report.add_argument("output_report", type=Path, nargs="?")
    reverify_report.add_argument("--config", default="config.toml")
    reverify_report.add_argument("--depth", type=int, default=20)
    reverify_report.add_argument("--multipv", type=int, default=8)
    reverify_report.add_argument("--kind", action="append", choices=["winning", "drawing"], default=[])
    reverify_report.add_argument("--max-confidence", type=int)
    reverify_report.add_argument("--max-records", type=int, default=0)
    reverify_report.add_argument("--include-hidden", action="store_true")
    reverify_report.add_argument("--win-cp", type=int, default=200)
    reverify_report.add_argument("--draw-floor-cp", type=int, default=-80)
    reverify_report.add_argument("--losing-cp", type=int, default=-150)
    reverify_report.add_argument("--min-gap-cp", type=int, default=150)
    reverify_report.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals/reverify"))
    reverify_report.add_argument("--profile-jsonl", type=Path)
    reextend_report = subparsers.add_parser("reextend-report")
    reextend_report.add_argument("files", nargs="*", type=Path)
    reextend_report.add_argument("--config", default="config.toml")
    reextend_report.add_argument("--glob", action="append", default=[])
    reextend_report.add_argument("--line-plies", type=int, default=5)
    reextend_report.add_argument("--max-plies", type=int, default=7)
    reextend_report.add_argument("--depth", type=int, default=10)
    reextend_report.add_argument("--multipv", type=int, default=6)
    reextend_report.add_argument("--extension-beam-width", type=int, default=2)
    reextend_report.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals/reextend"))
    reextend_report.add_argument("--profile-jsonl", type=Path)

    combine_reports = subparsers.add_parser("combine-reports")
    combine_reports.add_argument("reports", nargs="*", type=Path)
    combine_reports.add_argument("--glob")
    combine_reports.add_argument("--output", type=Path, default=Path("data/puzzles/chesscom_all_report.jsonl"))

    selfplay = subparsers.add_parser("selfplay")
    selfplay.add_argument("--config", default="config.toml")
    selfplay.add_argument("--games", type=int, default=10)
    selfplay.add_argument("--output-dir", type=Path, default=Path("data/raw/selfplay"))
    selfplay.add_argument("--prefix", default="selfplay")
    selfplay.add_argument("--depth", type=int, default=2)
    selfplay.add_argument("--skill-level", type=int)
    selfplay.add_argument("--uci-limit-strength", action="store_true")
    selfplay.add_argument("--uci-elo", type=int)
    selfplay.add_argument("--multipv", type=int, default=6)
    selfplay.add_argument("--max-plies", type=int, default=160)
    selfplay.add_argument("--temperature-cp", type=int, default=180)
    selfplay.add_argument("--blunder-chance", type=float, default=0.15)
    selfplay.add_argument("--resign-cp", type=int, default=700)
    selfplay.add_argument("--resign-moves", type=int, default=5)
    selfplay.add_argument("--keep-playing-after-no-schess-material", action="store_true")
    selfplay.add_argument("--seed", type=int)

    args = parser.parse_args()

    if args.command == "init-config":
        _init_config()
    elif args.command == "fetch-pychess":
        _fetch_pychess(Path(args.config), args.game_id)
    elif args.command == "discover-pychess":
        _discover_pychess(Path(args.config), args.url)
    elif args.command == "fetch-chesscom":
        _fetch_chesscom(Path(args.config), args.username, args.year, args.month)
    elif args.command == "fetch-chesscom-pgn4":
        _fetch_chesscom_pgn4(Path(args.config), args.game_id_or_url, args.cookie, args.debug_socket)
    elif args.command == "discover-chesscom-variants":
        _discover_chesscom_variants(Path(args.config), args.url)
    elif args.command == "inspect-chesscom-auth":
        _inspect_chesscom_auth(Path(args.config), args)
    elif args.command == "format-cookie":
        _format_cookie(args.input, args.output)
    elif args.command == "discover-chesscom-archive":
        _discover_chesscom_archive(Path(args.config), args)
    elif args.command == "fetch-chesscom-archive":
        _fetch_chesscom_archive(Path(args.config), args)
    elif args.command == "crawl-chesscom":
        _crawl_chesscom(Path(args.config), args)
    elif args.command == "chesscom-next-tactics":
        _chesscom_next_tactics(Path(args.config), args)
    elif args.command == "inspect-sources":
        _inspect_sources(args.files)
    elif args.command == "pipeline":
        _pipeline(Path(args.config), args.input)
    elif args.command == "solve":
        solve_jsonl(args.puzzles)
    elif args.command == "list-positions":
        _list_positions(Path(args.config), args.input)
    elif args.command == "inspect":
        _inspect(Path(args.config), args.input, args.move_number, args.side, args.fen, args.depth, args.multipv, args.eval_cache_dir)
    elif args.command == "select":
        _select(Path(args.config), args.input, args)
    elif args.command == "select-batch":
        _select_batch(Path(args.config), args)
    elif args.command == "suggest-fen":
        _suggest_fen(Path(args.config), args)
    elif args.command == "mutate-candidate":
        _mutate_candidate(Path(args.config), args)
    elif args.command == "retrograde-predecessors":
        _retrograde_predecessors(Path(args.config), args)
    elif args.command == "retrograde-chain":
        _retrograde_chain(Path(args.config), args)
    elif args.command == "review-html":
        _review_html(args.report_jsonl, args.output_html)
    elif args.command == "export-web":
        _export_web(args.report_jsonl, args.output_json)
    elif args.command == "enrich-mate-lines":
        _enrich_mate_lines(Path(args.config), args)
    elif args.command == "refresh-report-flags":
        _refresh_report_flags(args.input_report, args.output_report)
    elif args.command == "reverify-report":
        _reverify_report(Path(args.config), args)
    elif args.command == "reextend-report":
        _reextend_report(Path(args.config), args)
    elif args.command == "combine-reports":
        _combine_reports(args.reports, args.glob, args.output)
    elif args.command == "selfplay":
        _selfplay(Path(args.config), args)


def _init_config() -> None:
    source = Path("config.example.toml")
    target = Path("config.toml")
    if target.exists():
        print("config.toml already exists.")
        return
    shutil.copyfile(source, target)
    print("Created config.toml.")


def _fetch_pychess(config_path: Path, game_id: str) -> None:
    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("pychess", {})
    client = PychessClient(settings.get("base_url", "https://www.pychess.org"))
    downloaded = client.download_pgn(game_id, config.paths.raw_games)
    print(f"Wrote {downloaded.path}")


def _discover_pychess(config_path: Path, url: str) -> None:
    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("pychess", {})
    client = PychessClient(settings.get("base_url", "https://www.pychess.org"))
    for game_id in client.discover_game_ids_from_url(url):
        print(game_id)


def _fetch_chesscom(config_path: Path, username: str, year: int, month: int) -> None:
    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("chess_com", {})
    client = ChessComClient(settings.get("base_url", "https://api.chess.com/pub"))
    downloaded = client.download_month_pgn(username, year, month, config.paths.raw_games)
    print(f"Wrote {downloaded.path}")


def _fetch_chesscom_pgn4(
    config_path: Path,
    game_id_or_url: str,
    cookie: str | None,
    debug_socket: bool,
) -> None:
    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("chess_com", {})
    client = ChessComClient(settings.get("base_url", "https://api.chess.com/pub"))
    try:
        downloaded = client.download_variant_pgn4(
            game_id_or_url,
            config.paths.raw_games,
            cookie=cookie,
            debug_socket=debug_socket,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {downloaded.path}")


def _discover_chesscom_variants(config_path: Path, url: str) -> None:
    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("chess_com", {})
    client = ChessComClient(settings.get("base_url", "https://api.chess.com/pub"))
    for game_id in client.discover_variant_game_ids_from_url(url):
        print(game_id)


def _inspect_chesscom_auth(config_path: Path, args: argparse.Namespace) -> None:
    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("chess_com", {})
    cookie = args.cookie or __import__("os").getenv("CHESSCOM_COOKIE")
    if not cookie:
        raise SystemExit("Set CHESSCOM_COOKIE or pass --cookie for authenticated chess.com diagnostics.")
    client = ChessComClient(settings.get("base_url", "https://api.chess.com/pub"))
    diagnostics = client.inspect_auth(cookie=cookie)
    for key, value in diagnostics.items():
        print(f"{key}: {value}")


def _format_cookie(input_path: Path, output_path: Path) -> None:
    rows = []
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read()
    for raw_line in sample.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("cookie:"):
            line = line.partition(":")[2].strip()
        if not line:
            continue
        if "\t" in line:
            parsed = next(csv.reader([line], delimiter="\t"), [])
            if len(parsed) < 2:
                continue
            name = parsed[0].strip()
            value = parsed[1].strip()
        elif "=" in line and ";" not in line:
            name, _, value = line.partition("=")
            name = name.strip()
            value = value.strip().strip('"')
        else:
            for part in line.split(";"):
                name, separator, value = part.strip().partition("=")
                if separator and name:
                    rows.append((name, value.strip().strip('"')))
            continue
        if name:
            rows.append((name, value.strip('"')))

    deduped = {name: value for name, value in rows if name}
    if not deduped:
        raise SystemExit(f"No cookies found in {input_path}")

    output = "; ".join(f"{name}={value}" for name, value in sorted(deduped.items()))
    output_path.write_text(output, encoding="utf-8")
    print(f"Wrote {output_path} with {len(deduped)} cookie(s): {', '.join(sorted(deduped))}")


def _discover_chesscom_archive(config_path: Path, args: argparse.Namespace) -> None:
    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("chess_com", {})
    cookie = args.cookie or __import__("os").getenv("CHESSCOM_COOKIE")
    if not cookie:
        raise SystemExit("Set CHESSCOM_COOKIE or pass --cookie for authenticated chess.com archive search.")
    client = ChessComClient(settings.get("base_url", "https://api.chess.com/pub"))
    try:
        game_ids = client.discover_variant_archive(
            cookie=cookie,
            player_id=args.player_id,
            username=args.username,
            days=args.days,
            game_type=args.game_type,
            rating_type=args.rating_type,
            title=args.title,
            start_page=args.start_page,
            limit_pages=args.pages,
            archive_timeout=args.archive_timeout,
            debug=args.debug_socket,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    for game_id in game_ids:
        print(game_id)


def _fetch_chesscom_archive(config_path: Path, args: argparse.Namespace) -> None:
    import time

    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("chess_com", {})
    cookie, auth_user_id = _chesscom_auth(args)

    client = ChessComClient(settings.get("base_url", "https://api.chess.com/pub"))
    block_signature = _archive_block_signature(args)
    known_blocks = [] if args.no_archive_block_skip else _read_archive_blocks(args.archive_block_manifest, block_signature)
    page_size = 20
    page = args.start_page
    effective_page_budget = max(1, args.pages)
    effective_pages_done = 0
    discovered_ids: list[str] = []
    downloaded = 0
    skipped_existing = 0
    failed = 0
    pages_queried = 0
    pages_skipped = 0
    suggested_next_days: str | None = None

    while effective_pages_done < effective_page_budget:
        try:
            page_ids = client.discover_variant_archive(
                cookie=cookie,
                player_id=args.player_id,
                username=args.username,
                days=args.days,
                game_type=args.game_type,
                rating_type=args.rating_type,
                title=args.title,
                start_page=page,
                limit_pages=1,
                archive_timeout=args.archive_timeout,
                debug=args.debug_socket,
                auth_user_id=auth_user_id,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        pages_queried += 1
        if not page_ids:
            print(f"Archive page {page}: no games")
            break

        existing = []
        missing = []
        for game_id in page_ids:
            target = config.paths.raw_games / f"chesscom_{game_id}.pgn4.txt"
            if target.exists():
                existing.append(game_id)
            else:
                missing.append(game_id)

        skip_pages = 1
        skipped_block_ids: list[str] = []
        if not missing and known_blocks:
            skip_pages, skipped_block_ids = _known_archive_skip_match(page_ids, known_blocks, page_size)
        if not missing:
            boundary_ids = skipped_block_ids or page_ids
            suggested_next_days = suggested_next_days or _suggest_next_archive_days(
                boundary_ids,
                config.paths.raw_games,
            )
            if skip_pages > 1:
                print(
                    f"Archive page {page}: existing={len(existing)} to_download=0; "
                    f"matched known block, skipping {skip_pages} page(s)"
                )
                pages_skipped += skip_pages - 1
                skipped_existing += len(existing) * skip_pages
                page += skip_pages
            else:
                print(
                    f"Archive page {page}: discovered={len(page_ids)} existing={len(existing)} to_download=0; "
                    "existing date boundary reached"
                )
                discovered_ids.extend(page_ids)
                skipped_existing += len(existing)
                page += 1
            # A fully-known page marks the boundary of the useful date window.
            # Return control to the unattended runner so it can restart at page 0
            # with the older date range instead of probing the rest of this range.
            break
        print(f"Archive page {page}: discovered={len(page_ids)} existing={len(existing)} to_download={len(missing)}")
        effective_pages_done += 1
        skipped_existing += len(existing)
        discovered_ids.extend(page_ids)
        for index, game_id in enumerate(missing, start=1):
            try:
                result = client.download_variant_pgn4(game_id, config.paths.raw_games, cookie=cookie, auth_user_id=auth_user_id)
            except Exception as exc:
                failed += 1
                print(f"  [{index}/{len(missing)}] failed {game_id}: {exc}")
                continue
            downloaded += 1
            print(f"  [{index}/{len(missing)}] wrote {result.path}")
            if args.delay > 0 and index < len(missing):
                time.sleep(args.delay)
        page += 1

    if discovered_ids:
        _append_archive_block(args.archive_block_manifest, block_signature, args.start_page, pages_queried, discovered_ids)
    print(
        "Done. "
        f"downloaded={downloaded} skipped_existing={skipped_existing} failed={failed} "
        f"pages_queried={pages_queried} effective_pages={effective_pages_done} pages_skipped={pages_skipped} next_page={page}"
    )
    if suggested_next_days:
        print(f"suggested_next_days={suggested_next_days}")


def _archive_block_signature(args: argparse.Namespace) -> dict:
    # Date windows deliberately do not participate: archive pages shift when
    # the lower day boundary changes, but their game-ID sequences remain useful.
    return {
        "player_id": args.player_id,
        "username": args.username,
        "game_type": args.game_type,
        "rating_type": args.rating_type,
        "title": args.title,
    }

def _read_archive_blocks(path: Path, signature: dict) -> list[list[str]]:
    if not path.exists():
        return []
    blocks: list[list[str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        record_signature = record.get("signature") or {}
        # Backwards-compatible with manifests written before date windows were
        # excluded from the signature.
        if any(record_signature.get(key) != value for key, value in signature.items()):
            continue
        game_ids = record.get("game_ids")
        if isinstance(game_ids, list) and game_ids:
            blocks.append([str(game_id) for game_id in game_ids])
    blocks.sort(key=len, reverse=True)
    return blocks


def _append_archive_block(path: Path, signature: dict, start_page: int, pages: int, game_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "signature": signature,
        "start_page": start_page,
        "pages": pages,
        "game_ids": game_ids,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def _known_archive_skip_match(page_ids: list[str], known_blocks: list[list[str]], page_size: int) -> tuple[int, list[str]]:
    if not page_ids:
        return 1, []
    wanted = [str(game_id) for game_id in page_ids]
    first = wanted[0]
    for block in known_blocks:
        for offset, game_id in enumerate(block):
            if game_id != first:
                continue
            if block[offset:offset + len(wanted)] != wanted:
                continue
            remaining_games = len(block) - offset
            skip_pages = max(1, remaining_games // max(1, page_size))
            skip_games = skip_pages * max(1, page_size)
            return skip_pages, block[offset:offset + skip_games]
    return 1, []


def _suggest_next_archive_days(game_ids: list[str], raw_games_dir: Path) -> str | None:
    dates = [
        date
        for game_id in game_ids
        if (date := _read_chesscom_game_date(raw_games_dir / f"chesscom_{game_id}.pgn4.txt")) is not None
    ]
    if not dates:
        return None
    oldest = min(dates)
    age_days = (datetime.now(timezone.utc) - oldest).days
    # Add one day to avoid landing back inside the same saturated block when the
    # server uses integer day ranges.
    return f"{max(1, age_days + 1)}-9999"


def _read_chesscom_game_date(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("[Date "):
                    match = re.search(r'\[Date "(.+)"\]', line)
                    if not match:
                        return None
                    return _parse_chesscom_date(match.group(1))
                continue
    except OSError:
        return None
    return None


def _parse_chesscom_date(value: str) -> datetime | None:
    cleaned = re.sub(r"\s*\(.+\)\s*$", "", value).strip()
    for fmt in ("%a %b %d %Y %H:%M:%S GMT%z", "%a %b %d %Y %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None

def _inspect_sources(files: list[Path]) -> None:
    for path in files:
        for headers in read_headers(path):
            game_id = headers.get("GameNr", "-")
            site = headers.get("Site", "-")
            white = headers.get("White", "-")
            black = headers.get("Black", "-")
            variant = headers.get("Variant", "-")
            print(f"{path}\tGameNr={game_id}\tVariant={variant}\tWhite={white}\tBlack={black}\tSite={site}")


def _crawl_chesscom(config_path: Path, args: argparse.Namespace) -> None:
    import time
    from collections import deque

    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("chess_com", {})
    cookie = args.cookie or __import__("os").getenv("CHESSCOM_COOKIE")
    if not cookie:
        raise SystemExit("Set CHESSCOM_COOKIE or pass --cookie for authenticated chess.com crawl.")

    client = ChessComClient(settings.get("base_url", "https://api.chess.com/pub"))
    player_queue = deque((player_id, None) for player_id in args.player_id)
    player_queue.extend((None, username) for username in args.username)
    if not player_queue:
        raise SystemExit("Provide at least one --player-id or --username seed.")

    visited_players: set[int] = set()
    queued_usernames = {username.lower() for username in args.username}
    seen_games: set[str] = set()
    downloaded = 0
    skipped = 0
    failed = 0

    while player_queue and len(visited_players) < args.max_players and len(seen_games) < args.max_games:
        player_id, username = player_queue.popleft()
        if player_id is None and username:
            player_id = client.resolve_variant_player_id(cookie=cookie, username=username, debug=args.debug_socket)
            if player_id is None:
                print(f"Could not resolve username {username}")
                continue
        if player_id is None or player_id in visited_players:
            continue

        visited_players.add(player_id)
        label = username or str(player_id)
        print(f"Searching player {label} ({player_id})")
        try:
            game_ids = client.discover_variant_archive(
                cookie=cookie,
                player_id=player_id,
                days=args.days,
                game_type=args.game_type,
                rating_type=args.rating_type,
                title=args.title,
                start_page=args.start_page,
                limit_pages=args.pages,
                archive_timeout=args.archive_timeout,
                debug=args.debug_socket,
            )
        except Exception as exc:
            print(f"Archive search failed for {label}: {exc}")
            continue

        for game_id in game_ids:
            if len(seen_games) >= args.max_games:
                break
            if game_id in seen_games:
                continue
            seen_games.add(game_id)

            target = config.paths.raw_games / f"chesscom_{game_id}.pgn4.txt"
            if target.exists():
                skipped += 1
                print(f"  skip existing {game_id}")
            else:
                try:
                    result = client.download_variant_pgn4(game_id, config.paths.raw_games, cookie=cookie)
                except Exception as exc:
                    failed += 1
                    print(f"  failed {game_id}: {exc}")
                    continue
                downloaded += 1
                target = result.path
                print(f"  wrote {target}")
                if args.delay > 0:
                    time.sleep(args.delay)

            for headers in read_headers(target):
                for key in ("White", "Black"):
                    found_username = headers.get(key)
                    if not found_username:
                        continue
                    lowered = found_username.lower()
                    if lowered in queued_usernames:
                        continue
                    queued_usernames.add(lowered)
                    player_queue.append((None, found_username))

    print(
        "Done. "
        f"players={len(visited_players)} games={len(seen_games)} "
        f"downloaded={downloaded} skipped={skipped} failed={failed} queued={len(player_queue)}"
    )


def _chesscom_next_tactics(config_path: Path, args: argparse.Namespace) -> None:
    import time

    if args.games <= 0:
        raise SystemExit("games must be positive")

    config = load_config(config_path)
    settings = config.raw.get("sources", {}).get("chess_com", {})
    cookie, auth_user_id = _chesscom_auth(args)
    client = ChessComClient(settings.get("base_url", "https://api.chess.com/pub"))

    downloaded_files: list[Path] = []
    seen_ids: set[str] = set()
    page = args.start_page
    pages_done = 0
    failed = 0
    skipped_existing = 0

    while len(downloaded_files) < args.games and pages_done < args.pages:
        try:
            game_ids = client.discover_variant_archive(
                cookie=cookie,
                player_id=args.player_id,
                username=args.username,
                days=args.days,
                game_type=args.game_type,
                rating_type=args.rating_type,
                title=args.title,
                start_page=page,
                limit_pages=1,
                archive_timeout=args.archive_timeout,
                debug=args.debug_socket,
                auth_user_id=auth_user_id,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        print(f"archive page {page}: discovered {len(game_ids)} game(s)")
        pages_done += 1
        page += 1

        for game_id in game_ids:
            if game_id in seen_ids:
                continue
            seen_ids.add(game_id)
            target = config.paths.raw_games / f"chesscom_{game_id}.pgn4.txt"
            if target.exists():
                skipped_existing += 1
                continue
            try:
                result = client.download_variant_pgn4(game_id, config.paths.raw_games, cookie=cookie, debug_socket=args.debug_socket, auth_user_id=auth_user_id)
            except Exception as exc:
                failed += 1
                print(f"  failed {game_id}: {exc}")
                continue
            downloaded_files.append(result.path)
            print(f"  wrote {result.path} ({len(downloaded_files)}/{args.games})")
            if len(downloaded_files) >= args.games:
                break
            if args.delay > 0:
                time.sleep(args.delay)

    if not downloaded_files:
        raise SystemExit(
            "No new Chess.com games downloaded. "
            f"pages_searched={pages_done} skipped_existing={skipped_existing} failed={failed}"
        )

    batch_name = args.batch_name or f"chesscom_batch{_next_chesscom_batch_number():02d}"
    jsonl = Path("data/puzzles") / f"{batch_name}.jsonl"
    report = Path("data/puzzles") / f"{batch_name}_report.jsonl"
    html = Path("data/puzzles") / f"{batch_name}_review.html"

    _select_batch(
        config_path,
        argparse.Namespace(
            files=downloaded_files,
            glob="",
            start_index=0,
            limit=0,
            depth=args.depth,
            multipv=args.multipv,
            confirm_depth=args.confirm_depth,
            confirm_multipv=args.confirm_multipv,
            confirm_fast_depth=args.confirm_fast_depth,
            confirm_clear_gap_cp=args.confirm_clear_gap_cp,
            confirm_clear_margin_cp=args.confirm_clear_margin_cp,
            confirm_borderline_depth=args.confirm_borderline_depth,
            confirm_borderline_win_cp=args.confirm_borderline_win_cp,
            confirm_borderline_gap_cp=args.confirm_borderline_gap_cp,
            win_cp=200,
            draw_floor_cp=-80,
            losing_cp=-150,
            min_gap_cp=150,
            exclude_recaptures=False,
            extend_critical=True,
            max_plies=args.max_plies,
            extension_beam_width=args.extension_beam_width,
            allow_check_reply_first=False,
            include_standard_positions=False,
            output_jsonl=jsonl,
            report_jsonl=report,
            eval_cache_dir=args.eval_cache_dir,
            profile_jsonl=args.profile_jsonl,
        ),
    )
    _refresh_report_flags(report, None)
    _review_html(report, html)

    if not args.no_update_public:
        _combine_reports([], "data/puzzles/chesscom_batch*_report.jsonl", Path("data/puzzles/chesscom_all_report.jsonl"))
        _review_html(Path("data/puzzles/chesscom_all_report.jsonl"), Path("data/puzzles/chesscom_all_review.html"))
        _merge_into_all_report(report)
        _review_html(Path("data/puzzles/all_report.jsonl"), Path("data/puzzles/all_review.html"))
        _export_web(Path("data/puzzles/all_report.jsonl"), Path("web/public/puzzles.json"))
        _sync_web_to_docs()

    print(
        "Done. "
        f"downloaded={len(downloaded_files)} skipped_existing={skipped_existing} failed={failed} "
        f"batch={batch_name} report={report}"
    )


def _chesscom_auth(args: argparse.Namespace) -> tuple[str, int | None]:
    import os

    if getattr(args, "cookie", None):
        return args.cookie, _chesscom_auth_user_id(args, {})

    values = _read_auth_file(getattr(args, "access_token_file", None))
    token = os.getenv("CHESSCOM_ACCESS_TOKEN") or values.get("ACCESS_TOKEN") or values.get("TOKEN") or values.get("RAW")
    if token:
        token = token.strip().strip('"').strip("'")
        if token.lower().startswith("cookie:"):
            token = token.split(":", 1)[1].strip()
        cookie = token if ";" in token or "=" in token else f"ACCESS_TOKEN={token}"
        return cookie, _chesscom_auth_user_id(args, values)

    cookie = os.getenv("CHESSCOM_COOKIE")
    if cookie:
        return cookie, _chesscom_auth_user_id(args, {})

    raise SystemExit("Set CHESSCOM_ACCESS_TOKEN, provide access_token.txt, CHESSCOM_COOKIE, or --cookie.")


def _read_auth_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip().upper()] = value.strip()
        elif "RAW" not in values:
            values["RAW"] = line
    return values


def _chesscom_auth_user_id(args: argparse.Namespace, values: dict[str, str]) -> int | None:
    import os

    if getattr(args, "auth_user_id", None) is not None:
        return int(args.auth_user_id)
    value = os.getenv("CHESSCOM_USER_ID") or values.get("CHESSCOM_USER_ID") or values.get("USER_ID") or values.get("ID")
    return int(value) if value else None


def _next_chesscom_batch_number() -> int:
    max_batch = 0
    for path in Path("data/puzzles").glob("chesscom_batch*_report.jsonl"):
        match = re.match(r"chesscom_batch(\d+)_report\.jsonl$", path.name)
        if match:
            max_batch = max(max_batch, int(match.group(1)))
    return max_batch + 1


def _merge_into_all_report(new_report: Path) -> None:
    all_report = Path("data/puzzles/all_report.jsonl")
    inputs = [path for path in (all_report, new_report) if path.exists()]
    tmp = Path("data/puzzles/all_report.next.jsonl")
    _combine_reports(inputs, "", tmp)
    tmp.replace(all_report)


def _sync_web_to_docs() -> None:
    web_dir = Path("web")
    docs_dir = Path("docs")
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    shutil.copytree(web_dir, docs_dir)
    (docs_dir / "CNAME").write_text("www.schesspuzzles.com\n", encoding="ascii")
    (docs_dir / ".nojekyll").write_text("", encoding="ascii")
    print("Copied web/ to docs/ for GitHub Pages.")

def _pipeline(config_path: Path, input_path: Path | None) -> None:
    config = load_config(config_path)
    puzzler = VariantPuzzler(config)

    for directory in (config.paths.raw_games, config.paths.positions, config.paths.puzzles):
        directory.mkdir(parents=True, exist_ok=True)

    if input_path is None:
        print("No input file supplied yet. Use --input with a pychess JSON or PGN file.")
        return

    positions = config.paths.positions / "positions.epd"
    loose = config.paths.puzzles / "puzzles_loose.epd"
    strict = config.paths.puzzles / "puzzles_strict.epd"
    pgn = config.paths.puzzles / "puzzles.pgn"
    jsonl = config.paths.puzzles / "puzzles.jsonl"

    input_kind = _detect_input_kind(input_path)
    if input_kind == "json":
        puzzler.convert_pychess_json(input_path, positions)
    elif input_kind == "pgn":
        puzzler.convert_pgn(input_path, positions)
    else:
        raise ValueError(f"Unsupported input format: {input_path}")

    puzzler.find_puzzles(positions, loose, config.pipeline.loose_depth)
    puzzler.find_puzzles(loose, strict, config.pipeline.strict_depth)
    puzzler.export_pgn(strict, pgn)
    write_jsonl(read_epd(strict), jsonl)
    print(f"Wrote {pgn}")
    print(f"Wrote {jsonl}")


def _list_positions(config_path: Path, input_path: Path) -> None:
    config = load_config(config_path)
    for position in positions_from_pgn(input_path, config.engine.variant):
        print(
            f"ply={position.ply:02d} move={position.move_number} side={position.side} "
            f"prev={position.previous_move or '-'} prev_uci={position.previous_uci or '-'} fen={position.fen}"
        )


def _inspect(
    config_path: Path,
    input_path: Path,
    move_number: int | None,
    side: str | None,
    fen: str | None,
    depth: int,
    multipv: int,
    eval_cache_dir: Path | None,
) -> None:
    config = load_config(config_path)
    selector_config = SelectionConfig(depth=depth, multipv=multipv, eval_cache_dir=eval_cache_dir)
    if fen:
        from .selector import PositionRecord

        positions = [
            PositionRecord(
                ply=0,
                move_number=int(fen.split()[-1]),
                side=fen.split()[1],
                fen=fen,
                variant=config.engine.variant,
                site="",
                previous_move=None,
                previous_uci=None,
            )
        ]
    else:
        positions = positions_from_pgn(input_path, config.engine.variant)
    uci_path = config.paths.variant_puzzler / "uci.py"
    from .selector import _load_uci_engine

    engine = _load_uci_engine(uci_path, config.engine.path)
    for position in positions:
        if move_number is not None and position.move_number != move_number:
            continue
        if side is not None and position.side != side:
            continue
        print(
            f"\nply={position.ply} move={position.move_number} side={position.side} "
            f"prev={position.previous_move} prev_uci={position.previous_uci}"
        )
        print(position.fen)
        for item in evaluate_position(position, engine, selector_config):
            print(f"{item.san:10s} {item.move:8s} {item.score_cp:7d} pv={' '.join(item.pv[:6])}")


def _select(config_path: Path, input_path: Path, args: argparse.Namespace) -> None:
    config = load_config(config_path)
    selector_config = SelectionConfig(
        depth=args.depth,
        multipv=args.multipv,
        win_cp=args.win_cp,
        draw_floor_cp=args.draw_floor_cp,
        losing_cp=args.losing_cp,
        min_gap_cp=args.min_gap_cp,
        max_plies=args.max_plies,
        extension_beam_width=getattr(args, "extension_beam_width", 1),
        extend_critical=args.extend_critical,
        prefer_quiet_replies=not args.allow_check_reply_first,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=not args.include_standard_positions,
        confirm_depth=args.confirm_depth,
        confirm_multipv=args.confirm_multipv,
        confirm_fast_depth=getattr(args, "confirm_fast_depth", None),
        confirm_clear_gap_cp=getattr(args, "confirm_clear_gap_cp", 300),
        confirm_clear_margin_cp=getattr(args, "confirm_clear_margin_cp", 300),
        confirm_borderline_depth=getattr(args, "confirm_borderline_depth", None),
        confirm_borderline_win_cp=getattr(args, "confirm_borderline_win_cp", None),
        confirm_borderline_gap_cp=getattr(args, "confirm_borderline_gap_cp", None),
        rescreen_depth=getattr(args, "rescreen_depth", None),
        rescreen_multipv=getattr(args, "rescreen_multipv", None),
        rescreen_min_gap_cp=getattr(args, "rescreen_min_gap_cp", 80),
        rescreen_margin_cp=getattr(args, "rescreen_margin_cp", 120),
    )
    uci_path = config.paths.variant_puzzler / "uci.py"
    selections = select_tactics(
        positions_from_pgn(input_path, config.engine.variant),
        config.engine.path,
        selector_config,
        uci_path,
    )
    if args.exclude_recaptures:
        print("--exclude-recaptures is deprecated for batch review; recaptures are saved and hidden by default in HTML.")
    for selection in selections:
        second = selection.second
        second_text = f"{second.san} {second.score_cp:+d}" if second else "-"
        print(
            f"{selection.kind:8s} move={selection.position.move_number} side={selection.position.side} "
            f"best={selection.best.san} {selection.best.score_cp:+d} second={second_text} "
            f"flags={','.join(selection.flags) or '-'} "
            f"line={' '.join(selection.best.pv or [selection.best.move])} "
            f"fen={selection.position.fen}"
        )
    if args.output_jsonl:
        write_jsonl(
            [
                Puzzle(
                    fen=selection.position.fen,
                    moves=selection.best.pv or [selection.best.move],
                    variant=selection.position.variant,
                    source=selection.position.site,
                    tags=[selection.kind, *selection.flags],
                )
                for selection in selections
            ],
            args.output_jsonl,
        )
        print(f"Wrote {args.output_jsonl}")


def _select_batch(config_path: Path, args: argparse.Namespace) -> None:
    config = load_config(config_path)
    selector_config = SelectionConfig(
        depth=args.depth,
        multipv=args.multipv,
        win_cp=args.win_cp,
        draw_floor_cp=args.draw_floor_cp,
        losing_cp=args.losing_cp,
        min_gap_cp=args.min_gap_cp,
        max_plies=args.max_plies,
        extension_beam_width=getattr(args, "extension_beam_width", 1),
        extend_critical=args.extend_critical,
        prefer_quiet_replies=not args.allow_check_reply_first,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=not args.include_standard_positions,
        confirm_depth=args.confirm_depth,
        confirm_multipv=args.confirm_multipv,
        confirm_fast_depth=getattr(args, "confirm_fast_depth", None),
        confirm_clear_gap_cp=getattr(args, "confirm_clear_gap_cp", 300),
        confirm_clear_margin_cp=getattr(args, "confirm_clear_margin_cp", 300),
        confirm_borderline_depth=getattr(args, "confirm_borderline_depth", None),
        confirm_borderline_win_cp=getattr(args, "confirm_borderline_win_cp", None),
        confirm_borderline_gap_cp=getattr(args, "confirm_borderline_gap_cp", None),
        rescreen_depth=getattr(args, "rescreen_depth", None),
        rescreen_multipv=getattr(args, "rescreen_multipv", None),
        rescreen_min_gap_cp=getattr(args, "rescreen_min_gap_cp", 80),
        rescreen_margin_cp=getattr(args, "rescreen_margin_cp", 120),
        profile_jsonl=args.profile_jsonl,
    )

    files = args.files or sorted(Path().glob(args.glob))
    if args.start_index > 0:
        files = files[args.start_index :]
    files = files[: args.limit] if args.limit > 0 else files
    if not files:
        raise SystemExit("No input files selected.")

    positions = []
    loaded_files = 0
    failed_files = 0
    for path in files:
        try:
            file_positions = positions_from_pgn(path, config.engine.variant)
        except Exception as exc:
            failed_files += 1
            print(f"failed to parse {path}: {exc}")
            continue
        loaded_files += 1
        source = str(path)
        positions.extend(replace(position, site=position.site or source) for position in file_positions)
        print(f"loaded {path} positions={len(file_positions)}")

    uci_path = config.paths.variant_puzzler / "uci.py"
    selections = select_tactics(positions, config.engine.path, selector_config, uci_path)
    if args.exclude_recaptures:
        print("--exclude-recaptures is deprecated for batch review; recaptures are saved and hidden by default in HTML.")

    puzzles = [
        Puzzle(
            fen=selection.position.fen,
            moves=selection.best.pv or [selection.best.move],
            variant=selection.position.variant,
            source=selection.position.site,
            tags=[selection.kind, *_review_flags(selection)],
        )
        for selection in selections
    ]
    write_jsonl(puzzles, args.output_jsonl)
    _write_selection_report(selections, args.report_jsonl)

    print(
        "Done. "
        f"files={loaded_files} failed_files={failed_files} positions={len(positions)} "
        f"tactics={len(selections)} output={args.output_jsonl} report={args.report_jsonl}"
    )



def _suggest_fen(config_path: Path, args: argparse.Namespace) -> None:
    from .selector import PositionRecord, classify_position, confirm_selection, extend_selection, _load_uci_engine

    config = load_config(config_path)
    fields = args.fen.split()
    if len(fields) < 6:
        raise SystemExit("FEN must include side, castling, en-passant, halfmove, and fullmove fields.")

    selector_config = SelectionConfig(
        depth=args.depth,
        multipv=args.multipv,
        win_cp=args.win_cp,
        draw_floor_cp=args.draw_floor_cp,
        losing_cp=args.losing_cp,
        min_gap_cp=args.min_gap_cp,
        max_plies=args.max_plies,
        extension_beam_width=getattr(args, "extension_beam_width", 1),
        extend_critical=True,
        prefer_quiet_replies=not args.allow_check_reply_first,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=not args.include_standard_positions,
        confirm_depth=None,
        confirm_multipv=None,
        profile_jsonl=args.profile_jsonl,
    )
    extend_config = SelectionConfig(
        depth=args.extend_depth,
        multipv=args.extend_multipv or args.multipv,
        win_cp=args.win_cp,
        draw_floor_cp=args.draw_floor_cp,
        losing_cp=args.losing_cp,
        min_gap_cp=args.min_gap_cp,
        max_plies=args.max_plies,
        extension_beam_width=getattr(args, "extension_beam_width", 1),
        extend_critical=True,
        prefer_quiet_replies=not args.allow_check_reply_first,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=not args.include_standard_positions,
        confirm_depth=None,
        confirm_multipv=None,
        profile_jsonl=args.profile_jsonl,
        eval_context="extension",
    )
    position = PositionRecord(
        ply=0,
        move_number=int(fields[-1]),
        side=fields[1],
        fen=args.fen,
        variant=config.engine.variant,
        site=args.source,
        previous_move=None,
        previous_uci=None,
    )

    uci_path = config.paths.variant_puzzler / "uci.py"
    engine = _load_uci_engine(uci_path, config.engine.path)
    selection = classify_position(position, evaluate_position(position, engine, selector_config), selector_config)
    selections = []
    if selection:
        selection = confirm_selection(selection, engine, selector_config)
    if selection:
        selection = extend_selection(selection, engine, extend_config)
        selections.append(selection)

    puzzles = [
        Puzzle(
            fen=item.position.fen,
            moves=item.best.pv or [item.best.move],
            variant=item.position.variant,
            source=item.position.site,
            tags=[item.kind, *_review_flags(item), "suggested"],
        )
        for item in selections
    ]
    write_jsonl(puzzles, args.output_jsonl)
    _write_selection_report(selections, args.report_jsonl)

    if not selections:
        print("No tactic passed the high-depth candidate check.")
        return

    item = selections[0]
    second = item.second
    second_text = f"{second.san} {second.score_cp:+d}" if second else "-"
    print(
        f"{item.kind:8s} move={item.position.move_number} side={item.position.side} "
        f"best={item.best.san} {item.best.score_cp:+d} second={second_text} "
        f"flags={','.join(_review_flags(item)) or '-'} "
        f"line={' '.join(item.best.pv or [item.best.move])}"
    )
    print(f"Wrote {args.output_jsonl} and {args.report_jsonl}")

def _mutate_candidate(config_path: Path, args: argparse.Namespace) -> None:
    import pyffish
    from .selector import PositionRecord, classify_position, extend_selection, _load_uci_engine

    config = load_config(config_path)
    fens = _read_candidate_fens(args.inputs)
    if not fens:
        raise SystemExit("No FENs supplied.")

    pieces = [piece.strip() for piece in args.pieces.split(",") if piece.strip()]
    if not pieces:
        raise SystemExit("--pieces must contain at least one piece symbol.")

    selector_config = SelectionConfig(
        depth=args.depth,
        multipv=args.multipv,
        win_cp=args.win_cp,
        draw_floor_cp=args.draw_floor_cp,
        losing_cp=args.losing_cp,
        min_gap_cp=args.min_gap_cp,
        max_plies=args.max_plies,
        extension_beam_width=args.extension_beam_width,
        extend_critical=True,
        prefer_quiet_replies=not args.allow_check_reply_first,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=not args.include_standard_positions,
        confirm_depth=None,
        confirm_multipv=None,
        profile_jsonl=args.profile_jsonl,
    )
    extend_config = replace(
        selector_config,
        depth=args.extend_depth,
        multipv=args.extend_multipv or args.multipv,
        eval_context="extension",
    )

    uci_path = config.paths.variant_puzzler / "uci.py"
    engine = _load_uci_engine(uci_path, config.engine.path)
    selections = []
    tested = 0
    illegal = 0

    for base_index, base_fen in enumerate(fens, start=1):
        per_fen_tested = 0
        for mutation in _single_piece_mutations(base_fen, pieces):
            if args.max_tested_per_fen > 0 and per_fen_tested >= args.max_tested_per_fen:
                break
            try:
                legal_count = len(pyffish.legal_moves(config.engine.variant, mutation["fen"], []))
            except Exception:
                illegal += 1
                continue
            if legal_count < 2:
                illegal += 1
                continue

            per_fen_tested += 1
            tested += 1
            fields = mutation["fen"].split()
            source = f"{args.source_prefix}_{base_index:03d}_{mutation['piece']}{mutation['square']}"
            position = PositionRecord(
                ply=0,
                move_number=int(fields[-1]),
                side=fields[1],
                fen=mutation["fen"],
                variant=config.engine.variant,
                site=source,
                previous_move=None,
                previous_uci=None,
            )
            try:
                selection = classify_position(position, evaluate_position(position, engine, selector_config), selector_config)
                if selection:
                    selection = extend_selection(selection, engine, extend_config)
            except Exception as exc:
                print(f"failed mutation {source}: {exc}")
                continue
            if not selection:
                continue
            line = selection.best.pv or [selection.best.move]
            if len(line) < args.min_line_plies:
                continue
            reason = f"{selection.reason}; synthetic mutation add {mutation['piece']}@{mutation['square']}"
            selections.append(
                replace(
                    selection,
                    reason=reason,
                    flags=tuple([*selection.flags, "suggested", "synthetic", "mutated-kernel"]),
                )
            )
            print(
                f"hit {source}: {selection.kind} best={selection.best.san} "
                f"score={selection.best.score_cp:+d} line_plies={len(line)}"
            )

    puzzles = [
        Puzzle(
            fen=item.position.fen,
            moves=item.best.pv or [item.best.move],
            variant=item.position.variant,
            source=item.position.site,
            tags=[item.kind, *_review_flags(item), "suggested", "synthetic", "mutated-kernel"],
        )
        for item in selections
    ]
    write_jsonl(puzzles, args.output_jsonl)
    _write_selection_report(selections, args.report_jsonl)
    print(
        "Done. "
        f"base_fens={len(fens)} tested={tested} illegal_or_terminal={illegal} "
        f"hits={len(selections)} output={args.output_jsonl} report={args.report_jsonl}"
    )




def _retrograde_chain(config_path: Path, args: argparse.Namespace) -> None:
    from .selector import PositionRecord, classify_position, extend_selection, _load_uci_engine

    config = load_config(config_path)
    beam = [{"fen": args.fen, "chain": []}]
    all_nodes = []
    seen_fens = {args.fen}

    for step in range(args.steps):
        capture_spec = _step_option(args.capture_pieces, step, "p,n,b,r,q,h,e")
        san_regex = _step_option(args.san_regex, step, None)
        next_nodes = []
        for node in beam:
            predecessors = _find_retrograde_predecessors(
                config.engine.variant,
                node["fen"],
                include_captures=args.captures,
                capture_piece_symbols=[piece.strip() for piece in capture_spec.split(",") if piece.strip()],
                san_regex=san_regex,
                max_results=args.max_results_per_node,
            )
            for predecessor in predecessors:
                if predecessor["fen"] in seen_fens:
                    continue
                seen_fens.add(predecessor["fen"])
                chain_step = {
                    "san": predecessor["san"],
                    "move": predecessor["move_to_target"],
                    "target_fen": predecessor["target_fen"],
                    "restored_capture": predecessor.get("restored_capture", ""),
                }
                next_nodes.append({"fen": predecessor["fen"], "chain": [chain_step, *node["chain"]]})
        next_nodes.sort(key=_retrograde_chain_score, reverse=True)
        if args.beam_width > 0:
            next_nodes = next_nodes[: args.beam_width]
        all_nodes.extend({"step": step + 1, **node} for node in next_nodes)
        beam = next_nodes
        print(f"step {step + 1}: kept={len(beam)} total_nodes={len(all_nodes)} filter_capture={capture_spec} filter_san={san_regex or '-'}")
        if not beam:
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in all_nodes:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {args.output} with {len(all_nodes)} retrograde node(s)")

    if not args.evaluate:
        for row in beam[:10]:
            line = " ".join(step["san"] for step in row["chain"])
            print(f"candidate fen={row['fen']} retro_line={line}")
        return

    selector_config = SelectionConfig(
        depth=args.depth,
        multipv=args.multipv,
        win_cp=args.win_cp,
        draw_floor_cp=args.draw_floor_cp,
        losing_cp=args.losing_cp,
        min_gap_cp=args.min_gap_cp,
        max_plies=args.max_plies,
        extension_beam_width=args.extension_beam_width,
        extend_critical=True,
        prefer_quiet_replies=not args.allow_check_reply_first,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=not args.include_standard_positions,
        confirm_depth=None,
        confirm_multipv=None,
        profile_jsonl=args.profile_jsonl,
    )
    extend_config = replace(
        selector_config,
        depth=args.extend_depth,
        multipv=args.extend_multipv or args.multipv,
        eval_context="extension",
    )
    uci_path = config.paths.variant_puzzler / "uci.py"
    engine = _load_uci_engine(uci_path, config.engine.path)
    selections = []
    for index, node in enumerate(beam, start=1):
        fields = node["fen"].split()
        if len(fields) < 6:
            continue
        position = PositionRecord(
            ply=0,
            move_number=int(fields[-1]),
            side=fields[1],
            fen=node["fen"],
            variant=config.engine.variant,
            site=f"{args.source_prefix}_{index:03d}",
            previous_move=None,
            previous_uci=None,
        )
        try:
            selection = classify_position(position, evaluate_position(position, engine, selector_config), selector_config)
            if selection:
                selection = extend_selection(selection, engine, extend_config)
        except Exception as exc:
            print(f"failed retrograde candidate {index}: {exc}")
            continue
        if not selection:
            continue
        intended_move = node["chain"][0]["move"] if node.get("chain") else ""
        if intended_move and selection.best.move != intended_move and not args.allow_other_first_move:
            continue
        line = selection.best.pv or [selection.best.move]
        if len(line) < args.min_line_plies:
            continue
        retro_line = " ".join(step["san"] for step in node["chain"])
        selections.append(
            replace(
                selection,
                reason=f"{selection.reason}; retrograde chain {retro_line}",
                flags=tuple([*selection.flags, "suggested", "synthetic", "retrograde"]),
            )
        )
        print(
            f"hit {position.site}: {selection.kind} best={selection.best.san} "
            f"score={selection.best.score_cp:+d} retro_line={retro_line}"
        )

    puzzles = [
        Puzzle(
            fen=item.position.fen,
            moves=item.best.pv or [item.best.move],
            variant=item.position.variant,
            source=item.position.site,
            tags=[item.kind, *_review_flags(item), "suggested", "synthetic", "retrograde"],
        )
        for item in selections
    ]
    write_jsonl(puzzles, args.output_jsonl)
    _write_selection_report(selections, args.report_jsonl)
    print(f"Wrote {args.output_jsonl} and {args.report_jsonl} with {len(selections)} tactic(s)")


def _step_option(values: list[str], step: int, default: str | None) -> str | None:
    if not values:
        return default
    if step < len(values):
        return values[step]
    return values[-1]


def _retrograde_chain_score(node: dict) -> tuple[int, int, str]:
    chain = node.get("chain", [])
    checks = sum(1 for item in chain if "+" in item.get("san", "") or "#" in item.get("san", ""))
    captures = sum(1 for item in chain if "x" in item.get("san", ""))
    return (checks, captures, node.get("fen", ""))
def _retrograde_predecessors(config_path: Path, args: argparse.Namespace) -> None:
    import pyffish

    config = load_config(config_path)
    results = _find_retrograde_predecessors(
        config.engine.variant,
        args.fen,
        include_captures=args.captures,
        capture_piece_symbols=[piece.strip() for piece in args.capture_pieces.split(",") if piece.strip()],
        san_regex=args.san_regex,
        max_results=args.max_results,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    for row in results[:20]:
        print(
            f"{row['san']:8s} {row['move_to_target']:7s} "
            f"capture={row.get('restored_capture') or '-':3s} fen={row['fen']}"
        )
    if len(results) > 20:
        print(f"... {len(results) - 20} more")
    print(f"Wrote {args.output} with {len(results)} predecessor(s)")


def _find_retrograde_predecessors(
    variant: str,
    target_fen: str,
    *,
    include_captures: bool,
    capture_piece_symbols: list[str],
    san_regex: str | None,
    max_results: int,
) -> list[dict[str, str]]:
    import pyffish

    fields = target_fen.split()
    if len(fields) < 6:
        raise SystemExit(f"FEN must include all fields: {target_fen}")
    target_board, pockets = _split_board_and_pockets(fields[0])
    target_grid = _expand_board(target_board)
    target_side = fields[1]
    previous_side = _opposite_side(target_side)
    capture_pieces = _retro_capture_pieces(previous_side, capture_piece_symbols) if include_captures else [None]
    results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for dst_rank, row in enumerate(target_grid):
        for dst_file, piece in enumerate(row):
            if piece == "1" or _piece_side(piece) != previous_side:
                continue
            dst = _square_name(dst_file, dst_rank)
            for src_rank in range(8):
                for src_file in range(8):
                    if target_grid[src_rank][src_file] != "1":
                        continue
                    src = _square_name(src_file, src_rank)
                    for restored_capture in capture_pieces:
                        if restored_capture and _piece_side(restored_capture) == previous_side:
                            continue
                        predecessor_grid = [rank[:] for rank in target_grid]
                        predecessor_grid[src_rank][src_file] = piece
                        predecessor_grid[dst_rank][dst_file] = restored_capture or "1"
                        predecessor_fields = fields[:]
                        predecessor_fields[0] = _compress_board(predecessor_grid) + pockets
                        predecessor_fields[1] = previous_side
                        predecessor_fields[3] = "-"
                        predecessor_fields[4] = "0"
                        predecessor_fields[5] = _previous_fullmove(fields[5], previous_side)
                        predecessor_fen = " ".join(predecessor_fields)
                        try:
                            legal_moves = pyffish.legal_moves(variant, predecessor_fen, [])
                        except Exception:
                            continue
                        for move in legal_moves:
                            if not move.startswith(src + dst):
                                continue
                            try:
                                reached = pyffish.get_fen(variant, predecessor_fen, [move])
                            except Exception:
                                continue
                            if not _same_board_and_side(reached, target_fen):
                                continue
                            key = (predecessor_fen, move)
                            if key in seen:
                                continue
                            seen.add(key)
                            san = pyffish.get_san_moves(variant, predecessor_fen, [move])[-1]
                            if san_regex and not re.search(san_regex, san):
                                continue
                            results.append(
                                {
                                    "fen": predecessor_fen,
                                    "side": previous_side,
                                    "move_to_target": move,
                                    "san": san,
                                    "target_fen": target_fen,
                                    "restored_capture": restored_capture or "",
                                }
                            )
                            if max_results > 0 and len(results) >= max_results:
                                return results
    return results


def _same_board_and_side(left_fen: str, right_fen: str) -> bool:
    left = left_fen.split()
    right = right_fen.split()
    return len(left) >= 2 and len(right) >= 2 and left[0] == right[0] and left[1] == right[1]


def _previous_fullmove(fullmove: str, previous_side: str) -> str:
    try:
        number = int(fullmove)
    except ValueError:
        return fullmove
    if previous_side == "b":
        number = max(1, number - 1)
    return str(number)


def _retro_capture_pieces(previous_side: str, pieces: list[str]) -> list[str]:
    normalized = [piece.lower() for piece in pieces if len(piece) == 1]
    if previous_side == "b":
        return [piece.upper() for piece in normalized]
    return normalized


def _piece_side(piece: str) -> str:
    return "w" if piece.isupper() else "b"


def _opposite_side(side: str) -> str:
    return "b" if side == "w" else "w"


def _square_name(file_index: int, rank_index: int) -> str:
    return f"{chr(ord('a') + file_index)}{8 - rank_index}"
def _read_candidate_fens(inputs: list[str]) -> list[str]:
    fens: list[str] = []
    for item in inputs:
        path = Path(item)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    fens.append(line)
        else:
            fens.append(item.strip())
    return fens


def _single_piece_mutations(fen: str, pieces: list[str]) -> list[dict[str, str]]:
    fields = fen.split()
    if len(fields) < 6:
        raise SystemExit(f"FEN must include all fields: {fen}")
    board, pockets = _split_board_and_pockets(fields[0])
    grid = _expand_board(board)
    mutations: list[dict[str, str]] = []
    for piece in pieces:
        if len(piece) != 1:
            continue
        for rank_index, rank in enumerate(grid):
            for file_index, value in enumerate(rank):
                if value != "1":
                    continue
                mutated_grid = [row[:] for row in grid]
                mutated_grid[rank_index][file_index] = piece
                mutated_board = _compress_board(mutated_grid) + pockets
                mutated_fields = [mutated_board, *fields[1:]]
                square = f"{chr(ord('a') + file_index)}{8 - rank_index}"
                mutations.append({"fen": " ".join(mutated_fields), "piece": piece, "square": square})
    return mutations


def _split_board_and_pockets(board_field: str) -> tuple[str, str]:
    if "[" not in board_field:
        return board_field, ""
    board, _, rest = board_field.partition("[")
    return board, "[" + rest


def _expand_board(board: str) -> list[list[str]]:
    grid: list[list[str]] = []
    for rank in board.split("/"):
        row: list[str] = []
        for char in rank:
            if char.isdigit():
                row.extend(["1"] * int(char))
            else:
                row.append(char)
        if len(row) != 8:
            raise SystemExit(f"Invalid FEN rank: {rank}")
        grid.append(row)
    if len(grid) != 8:
        raise SystemExit(f"Invalid FEN board: {board}")
    return grid


def _compress_board(grid: list[list[str]]) -> str:
    ranks: list[str] = []
    for row in grid:
        current = ""
        empties = 0
        for char in row:
            if char == "1":
                empties += 1
            else:
                if empties:
                    current += str(empties)
                    empties = 0
                current += char
        if empties:
            current += str(empties)
        ranks.append(current)
    return "/".join(ranks)
def _write_selection_report(selections, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for selection in selections:
            second = selection.second
            record = {
                "kind": selection.kind,
                "move_number": selection.position.move_number,
                "side": selection.position.side,
                "best_san": selection.best.san,
                "best_uci": selection.best.move,
                "best_score_cp": selection.best.score_cp,
                "second_san": second.san if second else None,
                "second_uci": second.move if second else None,
                "second_score_cp": second.score_cp if second else None,
                "flags": _review_flags(selection),
                "line": selection.best.pv or [selection.best.move],
                "fen": selection.position.fen,
                "source": selection.position.site,
                "reason": selection.reason,
            }
            handle.write(json.dumps(_enrich_report_record(record), ensure_ascii=False) + "\n")

def _review_flags(selection) -> list[str]:
    flags = list(selection.flags)
    if _previous_move_was_check(selection):
        flags.append("check-evasion")
    return _derived_review_flags(
        flags,
        fen=selection.position.fen,
        line=selection.best.pv or [selection.best.move],
        best_san=selection.best.san,
        best_uci=selection.best.move,
        second_san=selection.second.san if selection.second else None,
    )


def _refresh_report_flags(input_report: Path, output_report: Path | None) -> None:
    output_report = output_report or input_report
    records = []
    with input_report.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            records.append(_enrich_report_record(json.loads(line)))

    output_report.parent.mkdir(parents=True, exist_ok=True)
    with output_report.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote {output_report} with {len(records)} refreshed tactic(s)")


def _reverify_report(config_path: Path, args: argparse.Namespace) -> None:
    from .selector import PositionRecord, classify_position, _load_uci_engine

    output_report = args.output_report or args.input_report
    config = load_config(config_path)
    hidden_flags = {"standard-like", "trivial-recapture", "trivial-capture", "trivial-capture-cleanup", "check-evasion", "manual-reject", "failed-reverify"}
    kinds = set(args.kind or [])
    selector_config = SelectionConfig(
        depth=args.depth,
        multipv=args.multipv,
        win_cp=args.win_cp,
        draw_floor_cp=args.draw_floor_cp,
        losing_cp=args.losing_cp,
        min_gap_cp=args.min_gap_cp,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=False,
        profile_jsonl=args.profile_jsonl,
        eval_context="reverify",
    )
    uci_path = config.paths.variant_puzzler / "uci.py"
    engine = _load_uci_engine(uci_path, config.engine.path)

    records: list[dict] = []
    checked = 0
    passed = 0
    failed = 0
    skipped = 0
    with args.input_report.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = _enrich_report_record(json.loads(line))
            flags = set(record.get("flags") or [])
            if not args.include_hidden and flags & hidden_flags:
                skipped += 1
                records.append(record)
                continue
            if kinds and record.get("kind") not in kinds:
                skipped += 1
                records.append(record)
                continue
            if args.max_confidence is not None and int(record.get("quality", {}).get("confidence") or 0) > args.max_confidence:
                skipped += 1
                records.append(record)
                continue
            if args.max_records and checked >= args.max_records:
                skipped += 1
                records.append(record)
                continue

            checked += 1
            fen = record.get("fen", "")
            fields = fen.split()
            position = PositionRecord(
                ply=0,
                move_number=int(record.get("move_number") or (fields[-1] if len(fields) >= 6 else 0) or 0),
                side=record.get("side") or (fields[1] if len(fields) > 1 else "w"),
                fen=fen,
                variant="seirawan",
                site=record.get("source", ""),
                previous_move=None,
                previous_uci=None,
            )
            try:
                selection = classify_position(position, evaluate_position(position, engine, selector_config), selector_config)
            except Exception as exc:
                selection = None
                record["reverify"] = {"status": "error", "depth": args.depth, "multipv": args.multipv, "error": str(exc)}

            if selection and selection.kind == record.get("kind") and selection.best.move == record.get("best_uci"):
                passed += 1
                second = selection.second
                record["best_san"] = selection.best.san
                record["best_score_cp"] = selection.best.score_cp
                record["second_san"] = second.san if second else None
                record["second_uci"] = second.move if second else None
                record["second_score_cp"] = second.score_cp if second else None
                record["reverify"] = {
                    "status": "passed",
                    "depth": args.depth,
                    "multipv": args.multipv,
                    "best_uci": selection.best.move,
                    "best_score_cp": selection.best.score_cp,
                    "second_uci": second.move if second else None,
                    "second_score_cp": second.score_cp if second else None,
                }
                reason = str(record.get("reason") or "")
                marker = f"reverified at depth {args.depth}"
                if marker not in reason:
                    record["reason"] = f"{reason}; {marker}" if reason else marker
            else:
                failed += 1
                flags = list(record.get("flags") or [])
                if "failed-reverify" not in flags:
                    flags.append("failed-reverify")
                record["flags"] = flags
                if "reverify" not in record:
                    record["reverify"] = {
                        "status": "failed",
                        "depth": args.depth,
                        "multipv": args.multipv,
                        "expected_kind": record.get("kind"),
                        "expected_best_uci": record.get("best_uci"),
                        "actual_kind": selection.kind if selection else None,
                        "actual_best_uci": selection.best.move if selection else None,
                        "actual_best_score_cp": selection.best.score_cp if selection else None,
                    }
            records.append(_enrich_report_record(record))

    output_report.parent.mkdir(parents=True, exist_ok=True)
    with output_report.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(
        f"Reverified {checked} record(s): passed={passed} failed={failed} skipped={skipped}. "
        f"Wrote {output_report}"
    )

def _enrich_mate_lines(config_path: Path, args: argparse.Namespace) -> None:
    import pyffish
    from .selector import PositionRecord, _load_uci_engine

    output_report = args.output_report or args.input_report
    config = load_config(config_path)
    selector_config = SelectionConfig(
        depth=args.depth,
        multipv=args.multipv,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=False,
        eval_context="mate_line",
    )
    uci_path = config.paths.variant_puzzler / "uci.py"
    engine = _load_uci_engine(uci_path, config.engine.path)

    records: list[dict] = []
    checked = 0
    enriched = 0
    skipped = 0
    with args.input_report.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = _enrich_report_record(json.loads(line))
            if args.max_records and checked >= args.max_records:
                records.append(record)
                skipped += 1
                continue
            if not _record_has_mate_score(record):
                records.append(record)
                skipped += 1
                continue
            if _line_reaches_mate(record.get("fen", ""), record.get("line", [])):
                record.pop("bonus_mate_line", None)
                record.pop("bonus_mate_start_fen", None)
                record.pop("bonus_mate_line_san", None)
                record.pop("bonus_mate_alternative_first_moves", None)
                records.append(record)
                skipped += 1
                continue

            checked += 1
            try:
                start_fen = pyffish.get_fen("seirawan", record.get("fen", ""), record.get("line", []) or [])
                fields = start_fen.split()
                position = PositionRecord(
                    ply=0,
                    move_number=int(fields[-1]) if len(fields) >= 6 and fields[-1].isdigit() else int(record.get("move_number") or 0),
                    side=fields[1] if len(fields) > 1 else "w",
                    fen=start_fen,
                    variant="seirawan",
                    site=record.get("source", ""),
                    previous_move=None,
                    previous_uci=None,
                )
                evals = evaluate_position(position, engine, selector_config)
                best = evals[0] if evals else None
                if best and abs(best.score_cp) >= 90000:
                    san = _web_line_san_for_fen(start_fen, best.pv)
                    if "#" in san:
                        record["bonus_mate_start_fen"] = start_fen
                        record["bonus_mate_line"] = list(best.pv)
                        record["bonus_mate_line_san"] = san
                        record["bonus_mate_alternative_first_moves"] = _mate_alternative_first_moves(
                            start_fen,
                            record.get("side") or (record.get("fen", "").split()[1] if len(record.get("fen", "").split()) > 1 else "w"),
                            best.pv,
                            evals,
                            engine,
                            selector_config,
                        )
                        enriched += 1
            except Exception as exc:
                record["bonus_mate_error"] = str(exc)
            records.append(_enrich_report_record(record))

    output_report.parent.mkdir(parents=True, exist_ok=True)
    with output_report.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Mate-line enrichment checked={checked} enriched={enriched} skipped={skipped}. Wrote {output_report}")


def _record_has_mate_score(record: dict) -> bool:
    try:
        return abs(int(record.get("best_score_cp") or 0)) >= 90000
    except (TypeError, ValueError):
        return False


def _line_reaches_mate(fen: str, line: list[str]) -> bool:
    if not fen or not line:
        return False
    san = _web_line_san_for_fen(fen, line)
    return "#" in san


def _mate_alternative_first_moves(start_fen: str, solver_side: str, pv: list[str], evals, engine, config: SelectionConfig) -> list[dict]:
    import pyffish
    if not pv:
        return []
    side_to_move = start_fen.split()[1] if len(start_fen.split()) > 1 else solver_side
    solver_fen = start_fen
    solver_evals = evals
    if side_to_move != solver_side:
        try:
            solver_fen = pyffish.get_fen("seirawan", start_fen, [pv[0]])
            fields = solver_fen.split()
            from .selector import PositionRecord
            position = PositionRecord(
                ply=0,
                move_number=int(fields[-1]) if len(fields) >= 6 and fields[-1].isdigit() else 0,
                side=fields[1] if len(fields) > 1 else solver_side,
                fen=solver_fen,
                variant="seirawan",
                site="",
                previous_move=None,
                previous_uci=None,
            )
            solver_evals = evaluate_position(position, engine, config)
        except Exception:
            return []
    if not solver_evals:
        return []
    best_score = solver_evals[0].score_cp
    alternatives = []
    for item in solver_evals:
        if item.score_cp == best_score and abs(item.score_cp) >= 90000:
            alternatives.append({"uci": item.move, "san": item.san})
    return alternatives

def _reextend_report(config_path: Path, args: argparse.Namespace) -> None:
    import pyffish
    from .selector import MoveEval, PositionRecord, Selection, extend_selection, _load_uci_engine

    config = load_config(config_path)
    files = list(args.files)
    for pattern in args.glob:
        files.extend(sorted(Path().glob(pattern)))
    files = [path for path in dict.fromkeys(files) if path.exists()]
    if not files:
        raise SystemExit("No report files selected.")

    uci_path = config.paths.variant_puzzler / "uci.py"
    engine = _load_uci_engine(uci_path, config.engine.path)
    selector_config = SelectionConfig(
        depth=args.depth,
        multipv=args.multipv,
        win_cp=200,
        draw_floor_cp=-80,
        losing_cp=-150,
        min_gap_cp=150,
        max_plies=args.max_plies,
        extension_beam_width=args.extension_beam_width,
        extend_critical=True,
        prefer_quiet_replies=True,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=True,
        profile_jsonl=args.profile_jsonl,
        eval_context="extension",
    )

    total_records = 0
    candidates = 0
    extended = 0
    for path in files:
        records: list[dict] = []
        file_candidates = 0
        file_extended = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                total_records += 1
                old_line = list(record.get("line") or [])
                if len(old_line) == args.line_plies:
                    candidates += 1
                    file_candidates += 1
                    selection = _record_to_selection(record, old_line)
                    try:
                        new_selection = extend_selection(selection, engine, selector_config)
                    except Exception as exc:
                        print(f"failed to re-extend {path} {record.get('source')} move {record.get('move_number')}: {exc}")
                        new_selection = selection
                    new_line = list(new_selection.best.pv or [])
                    if len(new_line) > len(old_line):
                        record["line"] = new_line
                        record["reason"] = f"{record.get('reason', '')}; re-extended to {len(new_line)} plies"
                        file_extended += 1
                        extended += 1
                records.append(_enrich_report_record(record))

        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if file_candidates or file_extended:
            print(f"{path}: candidates={file_candidates} extended={file_extended}")

    print(f"Done. files={len(files)} records={total_records} candidates={candidates} extended={extended}")


def _record_to_selection(record: dict, line: list[str]):
    from .selector import MoveEval, PositionRecord, Selection

    fen = record.get("fen", "")
    fields = fen.split()
    position = PositionRecord(
        ply=0,
        move_number=int(record.get("move_number") or (fields[-1] if fields else 0) or 0),
        side=record.get("side") or (fields[1] if len(fields) > 1 else "w"),
        fen=fen,
        variant="seirawan",
        site=record.get("source", ""),
        previous_move=None,
        previous_uci=None,
    )
    best = MoveEval(
        move=record.get("best_uci") or (line[0] if line else ""),
        san=record.get("best_san") or "",
        score_cp=int(record.get("best_score_cp") or 0),
        pv=line or [record.get("best_uci", "")],
    )
    second = None
    if record.get("second_uci"):
        second = MoveEval(
            move=record.get("second_uci"),
            san=record.get("second_san") or "",
            score_cp=int(record.get("second_score_cp") or 0),
            pv=[record.get("second_uci")],
        )
    return Selection(
        position=position,
        kind=record.get("kind") or "winning",
        best=best,
        second=second,
        reason=record.get("reason", ""),
        flags=tuple(record.get("flags") or ()),
    )

def _combine_reports(reports: list[Path], glob_pattern: str | None, output: Path) -> None:
    inputs = list(reports)
    if glob_pattern:
        inputs.extend(sorted(Path().glob(glob_pattern)))
    if not inputs:
        inputs = sorted(Path().glob("data/puzzles/chesscom_batch*_report.jsonl"))
    records: list[dict] = []
    seen: set[tuple] = set()
    for path in inputs:
        if path == output or not path.exists() or path.name.startswith(("confirm_", "checkflags_")):
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = _enrich_report_record(json.loads(line))
                key = (
                    record.get("source"),
                    record.get("fen"),
                    record.get("kind"),
                    record.get("best_uci"),
                    tuple(record.get("line", [])),
                )
                if key in seen:
                    continue
                seen.add(key)
                records.append(record)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote {output} with {len(records)} tactic(s) from {len(inputs)} report file(s)")

def _export_web(report_jsonl: Path, output_json: Path) -> None:
    hidden_flags = {"standard-like", "trivial-recapture", "trivial-capture", "trivial-capture-cleanup", "check-evasion", "manual-reject", "failed-reverify"}
    puzzles = []
    with report_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            flags = record.get("flags", [])
            if hidden_flags & set(flags):
                continue
            solution_line_san = _web_line_san(record)
            mate_line = _web_mate_line(record)
            mate_start_fen = str(record.get("bonus_mate_start_fen") or "")
            mate_line_san = str(record.get("bonus_mate_line_san") or (_web_line_san_for_fen(mate_start_fen, mate_line) if mate_line and mate_start_fen else ""))
            puzzles.append(
                {
                    "id": _web_puzzle_id(record),
                    "variant": "seirawan",
                    "fen": record.get("fen", ""),
                    "side": record.get("side"),
                    "move_number": record.get("move_number"),
                    "kind": record.get("kind"),
                    "solution": record.get("line", []),
                    "legal_moves": _web_legal_moves(record),
                    "solution_san": record.get("best_san"),
                    "solution_line_san": solution_line_san,
                    "mate_line": mate_line,
                    "mate_start_fen": mate_start_fen,
                    "mate_line_san": mate_line_san,
                    "mate_alternative_first_moves": record.get("bonus_mate_alternative_first_moves", []),
                    "source_url": record.get("source"),
                    "reason": record.get("reason"),
                    "scores": {
                        "best_cp": record.get("best_score_cp"),
                        "second_cp": record.get("second_score_cp"),
                        "second_san": record.get("second_san"),
                    },
                    "quality": record.get("quality", {}),
                    "material": record.get("material", {}),
                    "dedupe": record.get("dedupe", {}),
                    "tags": flags,
                    "categories": _web_categories(record, flags),
                    "hidden_by_default": bool(hidden_flags & set(flags)),
                }
            )

    payload = {
        "schema_version": 1,
        "generated_by": "schess_puzzles export-web",
        "count": len(puzzles),
        "puzzles": puzzles,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_json} with {len(puzzles)} puzzle(s)")

def _enrich_report_record(record: dict) -> dict:
    record = dict(record)
    line = _normalize_line(record.get("line", []))
    record["line"] = line
    record["flags"] = _derived_review_flags(
        record.get("flags", []),
        fen=record.get("fen", ""),
        line=line,
        best_san=record.get("best_san", ""),
        best_uci=record.get("best_uci", ""),
        second_san=record.get("second_san"),
    )
    record["material"] = _record_material_metadata(record, line)
    record["quality"] = _record_quality_metadata(record, line)
    record["dedupe"] = _record_dedupe_metadata(record, line)
    return record


def _normalize_line(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return [item.strip() for item in value.split() if item.strip()]
    return []


def _record_material_metadata(record: dict, line: list[str]) -> dict:
    fen = record.get("fen", "")
    side = record.get("side") or (fen.split()[1] if len(fen.split()) > 1 else "w")
    before = _material_advantage(_fen_board(fen), side) if fen else None
    after_first = _material_after_moves(fen, line[:1], side) if line else None
    after_line = _material_after_moves(fen, line, side) if line else None
    return {
        "side": side,
        "before": before,
        "after_first": after_first,
        "after_line": after_line,
        "swing_first": None if before is None or after_first is None else after_first - before,
        "swing_line": None if before is None or after_line is None else after_line - before,
    }


def _material_after_moves(fen: str, moves: list[str], side: str) -> int | None:
    if not fen:
        return None
    try:
        import pyffish

        final_fen = pyffish.get_fen("seirawan", fen, moves)
    except Exception:
        final_fen = _fallback_fen_after_first_move(fen, moves[:1]) if len(moves) == 1 else ""
    return _material_advantage(_fen_board(final_fen), side) if final_fen else None


def _fallback_fen_after_first_move(fen: str, moves: list[str]) -> str:
    if not moves or len(moves[0]) < 4:
        return ""
    board = _fen_board(fen)
    move = moves[0]
    source = move[:2]
    target = move[2:4]
    piece = board.pop(source, None)
    if not piece:
        return ""
    promotion = move[4].lower() if len(move) >= 5 and move[4].lower() in PIECE_VALUES else ""
    side = fen.split()[1] if len(fen.split()) > 1 else "w"
    board[target] = (promotion.upper() if side == "w" else promotion) if promotion else piece
    return _board_to_fen_piece_placement(board) + " " + " ".join(fen.split()[1:])


def _board_to_fen_piece_placement(board: dict[str, str]) -> str:
    rows = []
    for rank in range(8, 0, -1):
        empty = 0
        row = []
        for file_ord in range(ord("a"), ord("h") + 1):
            piece = board.get(f"{chr(file_ord)}{rank}")
            if piece:
                if empty:
                    row.append(str(empty))
                    empty = 0
                row.append(piece)
            else:
                empty += 1
        if empty:
            row.append(str(empty))
        rows.append("".join(row))
    return "/".join(rows)


def _record_quality_metadata(record: dict, line: list[str]) -> dict:
    best = _number_or_none(record.get("best_score_cp"))
    second = _number_or_none(record.get("second_score_cp"))
    gap = None if best is None or second is None else best - second
    flags = set(record.get("flags", []))
    if "manual-reject" in flags or "failed-reverify" in flags:
        return {
            "eval_gap_cp": gap,
            "line_plies": len(line),
            "confidence": 0,
            "bucket": "rejected",
        }
    material = record.get("material", {})
    score = 50
    if gap is not None:
        score += min(25, max(0, gap - 150) // 20)
    if "confirmed at depth" in str(record.get("reason", "")):
        score += 12
    if len(line) >= 5:
        score += 8
    elif len(line) == 1:
        score -= 5
    if material.get("swing_first") is not None and material.get("swing_line") is not None:
        if material["swing_first"] >= 3 and len(line) == 1:
            score -= 18
        elif material["swing_line"] > material["swing_first"]:
            score += 6
    for flag, penalty in {
        "standard-like": 20,
        "trivial-capture": 18,
        "trivial-capture-cleanup": 22,
        "trivial-recapture": 16,
        "check-evasion": 8,
    }.items():
        if flag in flags:
            score -= penalty
    score = max(0, min(100, int(score)))
    return {
        "eval_gap_cp": gap,
        "line_plies": len(line),
        "confidence": score,
        "bucket": _quality_bucket(score),
    }


def _quality_bucket(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _record_dedupe_metadata(record: dict, line: list[str]) -> dict:
    fen = record.get("fen", "")
    exact = {
        "fen": _canonical_report_fen(fen),
        "kind": record.get("kind"),
        "best_uci": record.get("best_uci"),
        "line": line,
    }
    family = {
        "kind": record.get("kind"),
        "best_san": _clean_san(record.get("best_san", "")),
        "line_plies": len(line),
        "material_swing_line": (record.get("material") or {}).get("swing_line"),
    }
    return {
        "exact_key": _short_hash(exact),
        "family_key": _short_hash(family),
    }


def _canonical_report_fen(fen: str) -> str:
    fields = fen.split()
    return " ".join(fields[:4])


def _clean_san(san: str) -> str:
    return re.sub(r"[+#?!]", "", str(san or ""))


def _short_hash(value: dict) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _number_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
def _web_line_san(record: dict) -> str:
    line = record.get("line", []) or []
    if not line:
        return ""
    try:
        import pyffish

        san_moves = pyffish.get_san_moves("seirawan", record.get("fen", ""), line)
    except Exception:
        return " ".join(line)
    return " ".join(san_moves)


WEB_LEGAL_MOVE_PUZZLE_IDS = {"94p6j", "wgyp7", "jdttv"}

def _web_legal_moves(record: dict) -> list[list[str]]:
    """Legal UCI moves for each playable state in the stored puzzle line.

    The browser uses this engine-authored data to distinguish a legal wrong
    move from an illegal one without attempting to reproduce all S-Chess rules.
    """
    if _web_puzzle_id(record) not in WEB_LEGAL_MOVE_PUZZLE_IDS:
        return []

    fen = str(record.get("fen") or "")
    line = _normalize_line(record.get("line", []))
    if not fen:
        return []
    try:
        import pyffish

        states: list[list[str]] = []
        current = fen
        for ply, move in enumerate(line):
            states.append(list(pyffish.legal_moves("seirawan", current, [])) if ply % 2 == 0 else None)
            current = pyffish.get_fen("seirawan", current, [move])
        return states
    except Exception:
        return []

def _web_line_san_for_fen(fen: str, line: list[str]) -> str:
    if not fen or not line:
        return ""
    try:
        import pyffish

        return " ".join(pyffish.get_san_moves("seirawan", fen, line))
    except Exception:
        return " ".join(line)

def _web_mate_line(record: dict) -> list[str]:
    return _normalize_line(record.get("bonus_mate_line", []))

def _web_categories(record: dict, flags: list[str]) -> dict:
    return {
        "phase": _web_phase(record),
        "evaluation": _web_evaluation(record),
        "motifs": _web_motifs(record, flags),
        "length": _web_length(record),
        "source": _web_source_type(record),
    }

def _web_source_type(record: dict) -> str:
    source = str(record.get("source") or "").lower()
    if "chess.com" in source or "pychess.org" in source:
        return "human-game"
    if "selfplay" in source or "local-selfplay" in source:
        return "engine-selfplay"
    return "manual-suggestion"


def _web_phase(record: dict) -> str:
    move_number = int(record.get("move_number") or _web_fen_move_number(record.get("fen", "")) or 0)
    if move_number and move_number <= 12:
        return "opening"
    if _web_is_endgame_fen(record.get("fen", "")):
        return "endgame"
    return "middlegame"


def _web_evaluation(record: dict) -> str:
    best_score = record.get("best_score_cp") or 0
    san = str(record.get("best_san") or "")
    line_san = str(record.get("line_san") or record.get("solution_line_san") or "")
    if (isinstance(best_score, (int, float)) and best_score >= 90000) or "#" in san or "#" in line_san:
        return "checkmate"
    if record.get("kind") == "drawing":
        return "equality"
    return "crushing" if best_score >= 600 else "advantage"


def _web_length(record: dict) -> str:
    plies = max(1, len(record.get("line", [])))
    if plies <= 1:
        return "one-move"
    if plies <= 5:
        return "medium"
    if plies <= 9:
        return "long"
    return "very-long"

def _web_motifs(record: dict, flags: list[str]) -> list[str]:
    motifs: set[str] = set()
    flag_set = set(flags)
    san = str(record.get("best_san") or "")
    line = record.get("line", []) or []
    first = str(line[0]) if line else str(record.get("best_uci") or "")

    if "check-evasion" in flag_set or _is_material_defensive_record(record):
        motifs.add("defensive-move")
    if flag_set & {"recapture", "trivial-recapture", "complex-recapture"}:
        motifs.add("recapture")
    if "+" in san and "#" not in san:
        motifs.add("check")
    if _web_has_promotion(record):
        motifs.add("promotion")
    if _web_has_double_attack(record):
        motifs.add("double-attack")
    if "/H" in san or "/E" in san or re.search(r"(^|[^a-zA-Z])[HE](x|[a-h]|\d|$)", san):
        motifs.add("fairy-piece")
    if len(first) >= 5 and first[4].lower() in {"h", "e"}:
        motifs.add("gating")
    motifs.update(_web_repetition_motifs(record))
    if san and "x" not in san and "+" not in san and "#" not in san:
        motifs.add("quiet-move")
    return sorted(motifs)

def _web_has_promotion(record: dict) -> bool:
    """Return true only for a real pawn promotion, never an H/E gating suffix."""
    fen = str(record.get("fen") or "")
    line = _normalize_line(record.get("line", []))
    if not fen or not line:
        return False
    try:
        import pyffish

        current = fen
        for move in line:
            if len(move) >= 5:
                piece = _fen_board(current).get(move[:2], "")
                if piece.lower() == "p" and move[3] in {"1", "8"}:
                    return True
            current = pyffish.get_fen("seirawan", current, [move])
    except Exception:
        return False
    return False


def _web_has_double_attack(record: dict) -> bool:
    """Recognize a line-backed fork, including a gating piece on its entry square.

    Geometric attacks alone are too broad. A qualifying line must subsequently
    capture one of the two attacked targets, so the label describes an actual
    material-winning double attack rather than a harmless pressure move.
    """
    fen = str(record.get("fen") or "")
    line = _normalize_line(record.get("line", []))
    if not fen or len(line) < 3 or len(line[0]) < 4 or len(line[2]) < 4:
        return False
    first, reply, continuation = line[:3]
    try:
        import pyffish

        side = fen.split()[1]
        after_first_fen = pyffish.get_fen("seirawan", fen, [first])
        after_first = _fen_board(after_first_fen)
        attacker_squares = [first[2:4]]
        if len(first) >= 5 and first[4].lower() in {"e", "h"}:
            attacker_squares.append(first[:2])

        for attacker_square in attacker_squares:
            attacker = after_first.get(attacker_square, "")
            if not attacker:
                continue
            targets: set[str] = set()
            valuable_targets = 0
            attacks_king = False
            for square, piece in after_first.items():
                if not _is_enemy_piece(piece, side) or not _attacks(attacker, attacker_square, square, after_first):
                    continue
                targets.add(square)
                if piece.lower() == "k":
                    attacks_king = True
                elif PIECE_VALUES.get(piece.lower(), 0) >= 3:
                    valuable_targets += 1
            if not (valuable_targets >= 2 or (attacks_king and valuable_targets >= 1)):
                continue

            before_continuation = pyffish.get_fen("seirawan", after_first_fen, [reply])
            board_before_capture = _fen_board(before_continuation)
            capture_target = continuation[2:4]
            moving_piece = board_before_capture.get(continuation[:2], "")
            captured_piece = board_before_capture.get(capture_target, "")
            if (
                moving_piece
                and not _is_enemy_piece(moving_piece, side)
                and _is_enemy_piece(captured_piece, side)
                and capture_target in targets
            ):
                return True
    except Exception:
        return False
    return False

def _is_material_defensive_record(record: dict) -> bool:
    """Identify only-move equality saves that preserve material throughout."""
    if record.get("kind") != "drawing":
        return False
    material = record.get("material") or {}
    before = material.get("before")
    best = record.get("best_score_cp")
    second = record.get("second_score_cp")
    if not all(isinstance(value, (int, float)) for value in (before, best, second)):
        return False
    if abs(best - before * 100) > 150 or second > -150:
        return False
    line = _normalize_line(record.get("line", []))
    if not line:
        return False
    try:
        import pyffish

        current = str(record.get("fen") or "")
        side = str(record.get("side") or current.split()[1])
        for move in line:
            current = pyffish.get_fen("seirawan", current, [move])
            if _material_advantage(_fen_board(current), side) != before:
                return False
    except Exception:
        return False
    return True

def _web_repetition_motifs(record: dict) -> set[str]:
    fen = str(record.get("fen") or "")
    line = _normalize_line(record.get("line", []))
    if not fen or len(line) < 4:
        return set()
    try:
        import pyffish

        san_moves = pyffish.get_san_moves("seirawan", fen, line)
        fens = [fen]
        current = fen
        for move in line:
            current = pyffish.get_fen("seirawan", current, [move])
            fens.append(current)
    except Exception:
        return set()

    keys: dict[tuple[str, str, str, str], int] = {}
    repeated_ranges: list[tuple[int, int]] = []
    for index, item in enumerate(fens):
        parts = item.split()
        if len(parts) < 4:
            continue
        key = (parts[0], parts[1], parts[2], parts[3])
        previous = keys.get(key)
        if previous is not None:
            repeated_ranges.append((previous, index))
        else:
            keys[key] = index
    if not repeated_ranges:
        return set()

    return {"perpetual-check"}


def _web_fen_move_number(fen: str) -> int:
    fields = fen.split()
    if not fields:
        return 0
    try:
        return int(fields[-1])
    except ValueError:
        return 0


def _web_is_endgame_fen(fen: str) -> bool:
    board = (fen.split(" ", 1)[0] if fen else "").split("[", 1)[0]
    pieces = [char for char in board if char.isalpha()]
    queens = sum(1 for piece in pieces if piece.lower() == "q")
    non_king_pawn = sum(1 for piece in pieces if piece.lower() not in {"k", "p"})
    return queens == 0 and non_king_pawn <= 4

def _web_puzzle_id(record: dict) -> str:
    explicit_id = str(record.get("id") or "").strip()
    if explicit_id:
        return explicit_id
    key = json.dumps(
        {
            "source": record.get("source"),
            "fen": record.get("fen"),
            "kind": record.get("kind"),
            "best_uci": record.get("best_uci"),
            "line": record.get("line", []),
        },
        sort_keys=True,
    )
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    value = int.from_bytes(digest[:6], "big")
    alphabet = "23456789abcdefghjkmnpqrstuvwxyz"
    chars = []
    for _ in range(5):
        value, index = divmod(value, len(alphabet))
        chars.append(alphabet[index])
    return "".join(chars)
def _selfplay(config_path: Path, args: argparse.Namespace) -> None:
    config = load_config(config_path)
    uci_path = config.paths.variant_puzzler / "uci.py"
    selfplay_config = SelfPlayConfig(
        games=args.games,
        variant=config.engine.variant,
        depth=args.depth,
        skill_level=args.skill_level,
        uci_limit_strength=args.uci_limit_strength,
        uci_elo=args.uci_elo,
        multipv=args.multipv,
        max_plies=args.max_plies,
        temperature_cp=args.temperature_cp,
        blunder_chance=args.blunder_chance,
        resign_cp=args.resign_cp,
        resign_moves=args.resign_moves,
        stop_after_no_schess_material=not args.keep_playing_after_no_schess_material,
        seed=args.seed,
        prefix=args.prefix,
    )
    paths = generate_selfplay_pgns(
        engine_path=config.engine.path,
        uci_module_path=uci_path,
        output_dir=args.output_dir,
        config=selfplay_config,
    )
    for path in paths:
        print(f"Wrote {path}")


def _derived_review_flags(
    flags: list[str],
    *,
    fen: str,
    line: list[str],
    best_san: str,
    best_uci: str,
    second_san: str | None,
) -> list[str]:
    factual_flags = [
        flag
        for flag in flags
        if flag not in {"trivial-recapture", "complex-recapture", "trivial-capture", "trivial-capture-cleanup", "standard-like"}
    ]
    derived = list(dict.fromkeys(factual_flags))
    if "check-evasion" not in derived and _is_side_to_move_in_check(fen):
        derived.append("check-evasion")
    if "recapture" in derived:
        if len(line or []) >= 5:
            derived.append("complex-recapture")
        else:
            derived.append("trivial-recapture")
    elif _is_trivial_capture_cleanup(fen, best_uci, best_san, line):
        derived.append("trivial-capture-cleanup")
    elif _is_trivial_capture(fen, best_uci, best_san, line):
        derived.append("trivial-capture")
    if _is_standard_like_record(fen, line, best_san, second_san):
        derived.append("standard-like")
    return derived


def _is_standard_like(selection) -> bool:
    return _is_standard_like_record(
        selection.position.fen,
        selection.best.pv or [selection.best.move],
        selection.best.san,
        selection.second.san if selection.second else None,
    )


def _is_standard_like_record(fen: str, line: list[str], best_san: str, second_san: str | None) -> bool:
    board = fen.split(" ", 1)[0].split("[", 1)[0]
    if any(piece in board for piece in "EeHh"):
        return False
    if _san_mentions_fairy_piece(best_san):
        return False
    if second_san and _san_mentions_fairy_piece(second_san):
        return False
    for move in line:
        if len(move) >= 5 and move[-1].lower() in {"e", "h"}:
            return False
    return True


PIECE_VALUES = {
    "p": 1,
    "n": 3,
    "b": 3,
    "r": 5,
    "h": 8,
    "q": 9,
    "e": 9,
    "k": 0,
}


def _is_trivial_capture_cleanup(fen: str, best_uci: str, best_san: str, line: list[str]) -> bool:
    """Detect a major fairy-piece capture followed by a cosmetic forced cleanup.

    This is deliberately narrow: it catches a Hawk/Elephant winning at least a
    rook, then an opposing Hawk/Elephant checking onto an immediate recapture
    square. Broader three-ply exchanges remain visible for review.
    """
    if len(line or []) != 3 or not _is_capture_at_start(fen, best_uci, best_san):
        return False
    side = fen.split()[1] if len(fen.split()) > 1 else "w"
    initial_board = _fen_board(fen)
    if initial_board.get(line[0][:2], "").lower() not in {"e", "h"}:
        return False
    before = _material_advantage(initial_board, side)
    after_first = _material_after_moves(fen, line[:1], side)
    after_line = _material_after_moves(fen, line, side)
    if after_first is None or after_line is None or after_first - before < 5:
        return False
    reply, cleanup = line[1], line[2]
    if len(reply) < 4 or len(cleanup) < 4 or cleanup[2:4] != reply[2:4]:
        return False
    try:
        import pyffish
        reply_fen = pyffish.get_fen("seirawan", fen, line[:1])
        if _fen_board(reply_fen).get(reply[:2], "").lower() not in {"e", "h"}:
            return False
        reply_san = pyffish.get_san_moves("seirawan", reply_fen, [reply])[0]
        cleanup_fen = pyffish.get_fen("seirawan", reply_fen, [reply])
        cleanup_san = pyffish.get_san_moves("seirawan", cleanup_fen, [cleanup])[0]
    except Exception:
        return False
    return "+" in reply_san and "x" in cleanup_san and after_line >= after_first

def _is_capture_at_start(fen: str, best_uci: str, best_san: str) -> bool:
    if "x" in best_san or len(best_uci) < 4:
        return True
    board = _fen_board(fen)
    side = fen.split()[1] if len(fen.split()) > 1 else "w"
    return _is_enemy_piece(board.get(best_uci[2:4]), side)

def _is_trivial_capture(fen: str, best_uci: str, best_san: str, line: list[str]) -> bool:
    if len(line or []) != 1 or len(best_uci) < 4:
        return False
    board = _fen_board(fen)
    source = best_uci[:2]
    target = best_uci[2:4]
    captured_piece = board.get(target)
    moving_piece = board.get(source)
    side = fen.split()[1] if len(fen.split()) > 1 else "w"
    if not moving_piece:
        return False
    if "x" not in best_san and not _is_enemy_piece(captured_piece, side):
        return False
    before = _material_advantage(board, side)
    after = dict(board)
    after.pop(source, None)
    promotion = best_uci[4].lower() if len(best_uci) >= 5 and best_uci[4].lower() in PIECE_VALUES else ""
    after[target] = (promotion.upper() if side == "w" else promotion) if promotion else moving_piece
    return _material_advantage(after, side) - before >= 3


def _fen_board(fen: str) -> dict[str, str]:
    board_part = fen.split(" ", 1)[0].split("[", 1)[0]
    board: dict[str, str] = {}
    for row_index, row in enumerate(board_part.split("/")):
        rank = 8 - row_index
        file_index = 0
        for char in row:
            if char.isdigit():
                file_index += int(char)
                continue
            square = f"{chr(ord('a') + file_index)}{rank}"
            board[square] = char
            file_index += 1
    return board


def _is_enemy_piece(piece: str | None, side: str) -> bool:
    if not piece:
        return False
    return piece.islower() if side == "w" else piece.isupper()


def _material_advantage(board: dict[str, str], side: str) -> int:
    white = sum(PIECE_VALUES.get(piece.lower(), 0) for piece in board.values() if piece.isupper())
    black = sum(PIECE_VALUES.get(piece.lower(), 0) for piece in board.values() if piece.islower())
    balance = white - black
    return balance if side == "w" else -balance


def _san_mentions_fairy_piece(san: str) -> bool:
    return bool(re.search(r"(^|[^a-zA-Z])[EH](?:x|[a-h]|\d|$)", san))


def _previous_move_was_check(selection) -> bool:
    previous = selection.position.previous_move or ""
    return previous.endswith("+") or previous.endswith("#") or _is_side_to_move_in_check(selection.position.fen)


def _is_side_to_move_in_check(fen: str) -> bool:
    try:
        side = fen.split()[1]
    except IndexError:
        return False
    board = _fen_board(fen)
    king = "K" if side == "w" else "k"
    king_square = next((square for square, piece in board.items() if piece == king), None)
    if king_square is None:
        return False
    enemy_is_upper = side == "b"
    return any(
        piece.isupper() == enemy_is_upper and _attacks(piece, source, king_square, board)
        for source, piece in board.items()
    )


def _attacks(piece: str, source: str, target: str, board: dict[str, str]) -> bool:
    lower = piece.lower()
    df = ord(target[0]) - ord(source[0])
    dr = int(target[1]) - int(source[1])
    adf = abs(df)
    adr = abs(dr)
    if lower == "p":
        direction = 1 if piece.isupper() else -1
        return adr == 1 and dr == direction and adf == 1
    if lower == "n":
        return (adf, adr) in {(1, 2), (2, 1)}
    if lower == "b":
        return adf == adr and _clear_ray(source, target, board)
    if lower == "r":
        return (df == 0 or dr == 0) and _clear_ray(source, target, board)
    if lower == "q":
        return (adf == adr or df == 0 or dr == 0) and _clear_ray(source, target, board)
    if lower == "k":
        return max(adf, adr) == 1
    if lower == "h":
        return (adf, adr) in {(1, 2), (2, 1)} or (adf == adr and _clear_ray(source, target, board))
    if lower == "e":
        return (adf, adr) in {(1, 2), (2, 1)} or ((df == 0 or dr == 0) and _clear_ray(source, target, board))
    return False


def _clear_ray(source: str, target: str, board: dict[str, str]) -> bool:
    df = ord(target[0]) - ord(source[0])
    dr = int(target[1]) - int(source[1])
    step_file = 0 if df == 0 else (1 if df > 0 else -1)
    step_rank = 0 if dr == 0 else (1 if dr > 0 else -1)
    file_ord = ord(source[0]) + step_file
    rank = int(source[1]) + step_rank
    while f"{chr(file_ord)}{rank}" != target:
        if f"{chr(file_ord)}{rank}" in board:
            return False
        file_ord += step_file
        rank += step_rank
    return True


def _review_html(report_jsonl: Path, output_html: Path) -> None:
    records = []
    with report_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(_render_review_html(records), encoding="utf-8")
    print(f"Wrote {output_html} with {len(records)} tactic(s)")


def _render_review_html(records: list[dict]) -> str:
    payload = json.dumps(records, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>S-Chess Tactic Review</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f6f3ec;
  --ink: #1f2328;
  --muted: #667085;
  --light: #eee2c7;
  --dark: #7f9b79;
  --accent: #b3472f;
  --panel: #ffffff;
  font-family: "Segoe UI", Arial, sans-serif;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); }}
main {{ display: grid; grid-template-columns: minmax(320px, 48rem) minmax(18rem, 26rem); gap: 24px; padding: 24px; align-items: start; }}
.board-wrap {{ width: min(88vmin, 720px); }}
.board {{ display: grid; grid-template-columns: repeat(8, 1fr); grid-template-rows: repeat(8, 1fr); aspect-ratio: 1; border: 2px solid #2d2d2d; box-shadow: 0 10px 30px rgba(0,0,0,.14); }}
.sq {{ position: relative; display: grid; place-items: center; user-select: none; }}
.light {{ background: var(--light); }}
.dark {{ background: var(--dark); }}
.coord {{ position: absolute; left: 4px; bottom: 3px; font-size: 11px; color: rgba(0,0,0,.48); font-weight: 600; }}
.piece {{ width: 86%; height: 86%; object-fit: contain; pointer-events: none; }}
aside {{ background: var(--panel); border: 1px solid #ddd7ca; border-radius: 8px; padding: 18px; box-shadow: 0 8px 24px rgba(0,0,0,.08); }}
.topbar {{ display: flex; gap: 8px; align-items: center; margin-bottom: 16px; }}
button {{ border: 1px solid #c9c2b5; background: #fff; color: var(--ink); border-radius: 6px; padding: 8px 12px; font-weight: 650; cursor: pointer; }}
button:hover {{ border-color: var(--accent); }}
.primary {{ background: var(--accent); color: #fff; border-color: var(--accent); width: 100%; margin: 12px 0; }}
.counter {{ color: var(--muted); font-size: 14px; margin-left: auto; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }}
.score {{ color: var(--accent); font-weight: 750; }}
.meta {{ color: var(--muted); line-height: 1.45; overflow-wrap: anywhere; }}
.filters {{ display: grid; gap: 8px; margin: 0 0 12px; }}
.filter {{ display: flex; gap: 8px; align-items: center; color: var(--muted); font-size: 14px; }}
.filter input {{ width: 16px; height: 16px; }}
.line {{ font-family: Consolas, monospace; background: #f2efe8; padding: 10px; border-radius: 6px; overflow-wrap: anywhere; }}
.fen {{ font-family: Consolas, monospace; font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }}
.hidden {{ display: none; }}
@media (max-width: 840px) {{ main {{ grid-template-columns: 1fr; padding: 12px; }} .board-wrap {{ width: 100%; }} }}
</style>
</head>
<body>
<main>
  <section class="board-wrap"><div id="board" class="board"></div></section>
  <aside>
    <div class="topbar">
      <button id="prev" title="Previous tactic">Prev</button>
      <button id="next" title="Next tactic">Next</button>
      <span id="counter" class="counter"></span>
    </div>
    <div class="filters">
      <label class="filter"><input id="show-standard" type="checkbox"> Show standard-like tactics <span id="standard-count"></span></label>
      <label class="filter"><input id="show-recaptures" type="checkbox"> Show trivial recaptures <span id="recapture-count"></span></label>
      <label class="filter"><input id="show-captures" type="checkbox"> Show trivial captures <span id="capture-count"></span></label>
      <label class="filter"><input id="show-check-evasions" type="checkbox"> Show check evasions <span id="check-count"></span></label>
    </div>
    <h1 id="title"></h1>
    <p class="meta" id="source"></p>
    <button id="reveal" class="primary">Reveal Solution</button>
    <section id="solution" class="hidden">
      <p id="scores"></p>
      <p class="line" id="line"></p>
      <p class="meta" id="reason"></p>
    </section>
    <p class="fen" id="fen"></p>
  </aside>
</main>
<script>
const tactics = {payload};
let index = 0;
let revealed = false;
let showStandardLike = false;
let showRecaptures = false;
let showTrivialCaptures = false;
let showCheckEvasions = false;
const pieceBase = "../../assets/pieces";
const pieceNames = {{
  K: "K", Q: "Q", R: "R", B: "B", N: "N", P: "P",
  k: "K", q: "Q", r: "R", b: "B", n: "N", p: "P",
  E: "E", H: "H", e: "E", h: "H"
}};
function boardPart(fen) {{ return fen.split(" ")[0].split("[")[0]; }}
function visibleTactics() {{
  return tactics.filter(t => {{
    const flags = t.flags || [];
    if (!showStandardLike && flags.includes("standard-like")) return false;
    if (!showRecaptures && flags.includes("trivial-recapture")) return false;
    if (!showTrivialCaptures && flags.includes("trivial-capture")) return false;
    if (!showCheckEvasions && flags.includes("check-evasion")) return false;
    return true;
  }});
}}
function updateFilterCounts() {{
  const standard = tactics.filter(t => (t.flags || []).includes("standard-like")).length;
  const recaptures = tactics.filter(t => (t.flags || []).includes("trivial-recapture")).length;
  const captures = tactics.filter(t => (t.flags || []).includes("trivial-capture")).length;
  const checks = tactics.filter(t => (t.flags || []).includes("check-evasion")).length;
  document.getElementById("standard-count").textContent = `(${{standard}} hidden)`;
  document.getElementById("recapture-count").textContent = `(${{recaptures}} hidden)`;
  document.getElementById("capture-count").textContent = `(${{captures}} hidden)`;
  document.getElementById("check-count").textContent = `(${{checks}} hidden)`;
}}
function renderBoard(fen, side) {{
  const board = document.getElementById("board");
  board.innerHTML = "";
  const rows = boardPart(fen).split("/");
  const flip = side === "b";
  const squares = [];
  for (let r = 0; r < 8; r++) {{
    let file = 0;
    for (const ch of rows[r]) {{
      if (/\\d/.test(ch)) {{
        for (let i = 0; i < Number(ch); i++) squares.push({{piece: "", file: file++, rank: 8 - r}});
      }} else {{
        squares.push({{piece: ch, file: file++, rank: 8 - r}});
      }}
    }}
  }}
  const ordered = flip ? [...squares].reverse() : squares;
  for (const sq of ordered) {{
    const div = document.createElement("div");
    const name = String.fromCharCode(97 + sq.file) + sq.rank;
    div.className = "sq " + (((sq.file + sq.rank) % 2) ? "dark" : "light");
    if (sq.piece) {{
      const piece = document.createElement("img");
      const color = sq.piece === sq.piece.toUpperCase() ? "w" : "b";
      piece.src = `${{pieceBase}}/${{color}}${{pieceNames[sq.piece] || sq.piece.toUpperCase()}}.svg`;
      piece.alt = sq.piece;
      piece.className = "piece";
      div.appendChild(piece);
    }}
    const coord = document.createElement("span");
    coord.className = "coord";
    coord.textContent = name;
    div.appendChild(coord);
    board.appendChild(div);
  }}
}}
function show(i) {{
  const visible = visibleTactics();
  if (!visible.length) {{
    document.getElementById("board").innerHTML = "";
    document.getElementById("counter").textContent = "0 / 0";
    document.getElementById("title").textContent = "No tactics match the current filter";
  document.getElementById("source").textContent = `${{t.source || ""}} - move ${{t.move_number}}`;
    document.getElementById("solution").classList.add("hidden");
    document.getElementById("fen").textContent = "";
    return;
  }}
  index = (i + visible.length) % visible.length;
  revealed = false;
  const t = visible[index];
  renderBoard(t.fen, t.side);
  document.getElementById("counter").textContent = `${{index + 1}} / ${{visible.length}}`;
  document.getElementById("title").textContent = `${{t.kind}} tactic: ${{t.side === "w" ? "White" : "Black"}} to move`;
  document.getElementById("source").textContent = `${{t.source || ""}} - move ${{t.move_number}}`;
  document.getElementById("scores").innerHTML = `Best <span class="score">${{t.best_san}} (${{t.best_score_cp}} cp)</span><br>Second ${{t.second_san || "-"}} (${{t.second_score_cp ?? "-"}} cp)`;
  document.getElementById("line").textContent = `Line: ${{(t.line || []).join(" ")}}`;
  document.getElementById("reason").textContent = `${{t.reason}}${{t.flags?.length ? " | Flags: " + t.flags.join(", ") : ""}}`;
  document.getElementById("fen").textContent = t.fen;
  updateReveal();
}}
function updateReveal() {{
  document.getElementById("solution").classList.toggle("hidden", !revealed);
  document.getElementById("reveal").textContent = revealed ? "Hide Solution" : "Reveal Solution";
}}
document.getElementById("prev").onclick = () => show(index - 1);
document.getElementById("next").onclick = () => show(index + 1);
document.getElementById("reveal").onclick = () => {{ revealed = !revealed; updateReveal(); }};
document.getElementById("show-standard").onchange = (ev) => {{ showStandardLike = ev.target.checked; show(0); }};
document.getElementById("show-recaptures").onchange = (ev) => {{ showRecaptures = ev.target.checked; show(0); }};
document.getElementById("show-captures").onchange = (ev) => {{ showTrivialCaptures = ev.target.checked; show(0); }};
document.getElementById("show-check-evasions").onchange = (ev) => {{ showCheckEvasions = ev.target.checked; show(0); }};
document.addEventListener("keydown", (ev) => {{
  if (ev.key === "ArrowLeft") show(index - 1);
  if (ev.key === "ArrowRight") show(index + 1);
  if (ev.key === " ") {{ ev.preventDefault(); revealed = !revealed; updateReveal(); }}
}});
updateFilterCounts();
show(0);
</script>
</body>
</html>
"""


def _detect_input_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".pgn":
        return "pgn"

    with path.open("r", encoding="utf-8-sig") as handle:
        sample = handle.read(256).lstrip()

    if sample.startswith("{") or sample.startswith("[{"):
        return "json"
    if sample.startswith("[Event ") or "[Variant " in sample:
        return "pgn"

    return "unknown"


if __name__ == "__main__":
    main()
