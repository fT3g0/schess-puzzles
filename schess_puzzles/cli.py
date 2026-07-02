from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
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
    select.add_argument("--win-cp", type=int, default=200)
    select.add_argument("--draw-floor-cp", type=int, default=-80)
    select.add_argument("--losing-cp", type=int, default=-150)
    select.add_argument("--min-gap-cp", type=int, default=150)
    select.add_argument("--exclude-recaptures", action="store_true")
    select.add_argument("--extend-critical", action="store_true")
    select.add_argument("--max-plies", type=int, default=7)
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
    select_batch.add_argument("--win-cp", type=int, default=200)
    select_batch.add_argument("--draw-floor-cp", type=int, default=-80)
    select_batch.add_argument("--losing-cp", type=int, default=-150)
    select_batch.add_argument("--min-gap-cp", type=int, default=150)
    select_batch.add_argument("--exclude-recaptures", action="store_true")
    select_batch.add_argument("--extend-critical", action="store_true")
    select_batch.add_argument("--max-plies", type=int, default=5)
    select_batch.add_argument("--allow-check-reply-first", action="store_true")
    select_batch.add_argument("--include-standard-positions", action="store_true")
    select_batch.add_argument("--output-jsonl", type=Path, default=Path("data/puzzles/chesscom_batch20.jsonl"))
    select_batch.add_argument("--report-jsonl", type=Path, default=Path("data/puzzles/chesscom_batch20_report.jsonl"))
    select_batch.add_argument("--eval-cache-dir", type=Path, default=Path("data/cache/evals"))

    export_web = subparsers.add_parser("export-web")
    export_web.add_argument("report_jsonl", type=Path, nargs="?", default=Path("data/puzzles/all_report.jsonl"))
    export_web.add_argument("output_json", type=Path, nargs="?", default=Path("web/public/puzzles.json"))
    review_html = subparsers.add_parser("review-html")
    review_html.add_argument("report_jsonl", type=Path)
    review_html.add_argument("output_html", type=Path, nargs="?", default=Path("data/puzzles/review.html"))

    refresh_report_flags = subparsers.add_parser("refresh-report-flags")
    refresh_report_flags.add_argument("input_report", type=Path)
    refresh_report_flags.add_argument("output_report", type=Path, nargs="?")

    combine_reports = subparsers.add_parser("combine-reports")
    combine_reports.add_argument("reports", nargs="*", type=Path)
    combine_reports.add_argument("--glob", default="data/puzzles/chesscom_batch*_report.jsonl")
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
    elif args.command == "review-html":
        _review_html(args.report_jsonl, args.output_html)
    elif args.command == "export-web":
        _export_web(args.report_jsonl, args.output_json)
    elif args.command == "refresh-report-flags":
        _refresh_report_flags(args.input_report, args.output_report)
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
    cookie = args.cookie or __import__("os").getenv("CHESSCOM_COOKIE")
    if not cookie:
        raise SystemExit("Set CHESSCOM_COOKIE or pass --cookie for authenticated chess.com archive fetch.")

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

    print(f"Discovered {len(game_ids)} game(s).")
    downloaded = 0
    skipped = 0
    failed = 0
    for index, game_id in enumerate(game_ids, start=1):
        target = config.paths.raw_games / f"chesscom_{game_id}.pgn4.txt"
        if target.exists():
            skipped += 1
            print(f"[{index}/{len(game_ids)}] skip existing {target}")
            continue
        try:
            result = client.download_variant_pgn4(game_id, config.paths.raw_games, cookie=cookie)
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(game_ids)}] failed {game_id}: {exc}")
            continue
        downloaded += 1
        print(f"[{index}/{len(game_ids)}] wrote {result.path}")
        if args.delay > 0 and index < len(game_ids):
            time.sleep(args.delay)

    print(f"Done. downloaded={downloaded} skipped={skipped} failed={failed}")


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
        extend_critical=args.extend_critical,
        prefer_quiet_replies=not args.allow_check_reply_first,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=not args.include_standard_positions,
        confirm_depth=args.confirm_depth,
        confirm_multipv=args.confirm_multipv,
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
        extend_critical=args.extend_critical,
        prefer_quiet_replies=not args.allow_check_reply_first,
        eval_cache_dir=args.eval_cache_dir,
        skip_standard_positions=not args.include_standard_positions,
        confirm_depth=args.confirm_depth,
        confirm_multipv=args.confirm_multipv,
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


def _write_selection_report(selections, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for selection in selections:
            second = selection.second
            flags = _review_flags(selection)
            handle.write(
                json.dumps(
                    {
                        "kind": selection.kind,
                        "move_number": selection.position.move_number,
                        "side": selection.position.side,
                        "best_san": selection.best.san,
                        "best_uci": selection.best.move,
                        "best_score_cp": selection.best.score_cp,
                        "second_san": second.san if second else None,
                        "second_uci": second.move if second else None,
                        "second_score_cp": second.score_cp if second else None,
                        "flags": flags,
                        "line": selection.best.pv or [selection.best.move],
                        "fen": selection.position.fen,
                        "source": selection.position.site,
                        "reason": selection.reason,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


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
            record = json.loads(line)
            record["flags"] = _derived_review_flags(
                record.get("flags", []),
                fen=record.get("fen", ""),
                line=record.get("line", []),
                best_san=record.get("best_san", ""),
                best_uci=record.get("best_uci", ""),
                second_san=record.get("second_san"),
            )
            records.append(record)

    output_report.parent.mkdir(parents=True, exist_ok=True)
    with output_report.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote {output_report} with {len(records)} refreshed tactic(s)")


def _combine_reports(reports: list[Path], glob_pattern: str, output: Path) -> None:
    inputs = reports or sorted(Path().glob(glob_pattern))
    records: list[dict] = []
    seen: set[tuple] = set()
    for path in inputs:
        if path == output or not path.exists() or path.name.startswith(("confirm_", "checkflags_")):
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                record["flags"] = _derived_review_flags(
                    record.get("flags", []),
                    fen=record.get("fen", ""),
                    line=record.get("line", []),
                    best_san=record.get("best_san", ""),
                    best_uci=record.get("best_uci", ""),
                    second_san=record.get("second_san"),
                )
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
    hidden_flags = {"standard-like", "trivial-recapture", "trivial-capture", "check-evasion"}
    puzzles = []
    with report_jsonl.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            flags = _derived_review_flags(
                record.get("flags", []),
                fen=record.get("fen", ""),
                line=record.get("line", []),
                best_san=record.get("best_san", ""),
                best_uci=record.get("best_uci", ""),
                second_san=record.get("second_san"),
            )
            puzzles.append(
                {
                    "id": _web_puzzle_id(record),
                    "variant": "seirawan",
                    "fen": record.get("fen", ""),
                    "side": record.get("side"),
                    "move_number": record.get("move_number"),
                    "kind": record.get("kind"),
                    "solution": record.get("line", []),
                    "solution_san": record.get("best_san"),
                    "source_url": record.get("source"),
                    "reason": record.get("reason"),
                    "scores": {
                        "best_cp": record.get("best_score_cp"),
                        "second_cp": record.get("second_score_cp"),
                        "second_san": record.get("second_san"),
                    },
                    "tags": flags,
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


def _web_puzzle_id(record: dict) -> str:
    import hashlib

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
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
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
        if flag not in {"trivial-recapture", "complex-recapture", "trivial-capture", "standard-like"}
    ]
    derived = list(dict.fromkeys(factual_flags))
    if "check-evasion" not in derived and _is_side_to_move_in_check(fen):
        derived.append("check-evasion")
    if "recapture" in derived:
        if len(line or []) >= 5:
            derived.append("complex-recapture")
        else:
            derived.append("trivial-recapture")
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
    after = dict(board)
    after.pop(source, None)
    promotion = best_uci[4].lower() if len(best_uci) >= 5 and best_uci[4].lower() in PIECE_VALUES else ""
    after[target] = (promotion.upper() if side == "w" else promotion) if promotion else moving_piece
    return _material_advantage(after, side) >= 3


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
    document.getElementById("source").textContent = "";
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
  document.getElementById("source").textContent = `${{t.source || ""}} Â· move ${{t.move_number}}`;
  document.getElementById("scores").innerHTML = `Best <span class="score">${{t.best_san}} (${{t.best_score_cp}} cp)</span><br>Second ${{t.second_san || "-"}} (${{t.second_score_cp ?? "-"}} cp)`;
  document.getElementById("line").textContent = `Line: ${{(t.line || []).join(" ")}}`;
  document.getElementById("reason").textContent = `${{t.reason}}${{t.flags?.length ? " Â· " + t.flags.join(", ") : ""}}`;
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



