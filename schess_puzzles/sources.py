from __future__ import annotations

import base64
import html
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
import websocket


@dataclass(frozen=True)
class DownloadedFile:
    source: str
    path: Path


class PychessClient:
    def __init__(self, base_url: str = "https://www.pychess.org") -> None:
        self.base_url = base_url.rstrip("/")

    def download_json(self, game_id: str, target_dir: Path) -> DownloadedFile:
        url = urljoin(f"{self.base_url}/", f"api/game/{game_id}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"pychess_{game_id}.json"
        payload = response.json()
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return DownloadedFile(source="pychess", path=target)

    def download_pgn(self, game_id_or_url: str, target_dir: Path) -> DownloadedFile:
        game_id = extract_pychess_game_id(game_id_or_url)
        url = urljoin(f"{self.base_url}/", game_id)
        response = requests.get(url, timeout=30, headers=_headers())
        response.raise_for_status()

        pgn = extract_pychess_pgn(response.text)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"pychess_{game_id}.pgn"
        target.write_text(pgn, encoding="utf-8")
        return DownloadedFile(source="pychess", path=target)

    def discover_game_ids_from_url(self, url: str) -> list[str]:
        response = requests.get(url, timeout=30, headers=_headers())
        response.raise_for_status()
        return extract_pychess_game_ids(response.text)


class ChessComClient:
    def __init__(self, base_url: str = "https://api.chess.com/pub") -> None:
        self.base_url = base_url.rstrip("/")

    def download_month_pgn(self, username: str, year: int, month: int, target_dir: Path) -> DownloadedFile:
        url = f"{self.base_url}/player/{username}/games/{year}/{month:02d}/pgn"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"chesscom_{username}_{year}_{month:02d}.pgn"
        target.write_text(response.text, encoding="utf-8")
        return DownloadedFile(source="chess.com", path=target)

    def download_variant_pgn4(
        self,
        game_id_or_url: str,
        target_dir: Path,
        cookie: str | None = None,
        debug_socket: bool = False,
        auth_user_id: int | None = None,
    ) -> DownloadedFile:
        game_id = extract_chesscom_variant_game_id(game_id_or_url)
        cookie = cookie or os.getenv("CHESSCOM_COOKIE")

        if cookie:
            pgn4 = fetch_chesscom_pgn4_from_socket(
                game_id,
                cookie,
                timeout=10,
                debug=debug_socket,
                auth_user_id=auth_user_id,
            )
            if pgn4 is None:
                raise ValueError(
                    "Authenticated Chess.com PGN4 socket returned no game data; "
                    "this is usually temporary throttling and can be retried."
                )
        else:
            url = f"https://www.chess.com/variants/game/{game_id}"
            response = requests.get(url, timeout=30, headers=_headers())
            response.raise_for_status()
            pgn4 = extract_chesscom_pgn4(response.text)

        valid, reason = validate_chesscom_seirawan_pgn4(pgn4, expected_game_id=game_id)
        if not valid:
            raise ValueError(f"Rejected Chess.com PGN4 for game {game_id}: {reason}")

        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"chesscom_{game_id}.pgn4.txt"
        target.write_text(pgn4, encoding="utf-8")
        return DownloadedFile(source="chess.com", path=target)

    def discover_variant_game_ids_from_url(self, url: str) -> list[str]:
        response = requests.get(url, timeout=30, headers=_headers())
        response.raise_for_status()
        return extract_chesscom_variant_game_ids(response.text)

    def discover_variant_archive(
        self,
        *,
        cookie: str,
        player_id: int | None = None,
        username: str | None = None,
        days: str = "0-9999",
        game_type: str = "",
        rating_type: str = "",
        title: str = "seirawan",
        start_page: int = 0,
        limit_pages: int = 1,
        archive_timeout: int = 5,
        debug: bool = False,
        auth_user_id: int | None = None,
    ) -> list[str]:
        return discover_chesscom_variant_archive(
            cookie=cookie,
            player_id=player_id,
            username=username,
            days=days,
            game_type=game_type,
            rating_type=rating_type,
            title=title,
            start_page=start_page,
            limit_pages=limit_pages,
            archive_timeout=archive_timeout,
            debug=debug,
            auth_user_id=auth_user_id,
        )

    def resolve_variant_player_id(self, *, cookie: str, username: str, debug: bool = False) -> int | None:
        user_context = fetch_chesscom_user_context(cookie)
        ws = _open_chesscom_variants_socket(cookie)
        try:
            window_id = "schess-puzzles"
            _send_socket(ws, "connect-user", {**user_context, "clientVersion": "0.0.0"}, window_id)
            _wait_for_socket_mutation(ws, "user_connected", debug=debug)
            return _resolve_chesscom_variant_player_id(ws, username, window_id, debug=debug)
        finally:
            ws.close()

    def inspect_auth(self, *, cookie: str) -> dict:
        return inspect_chesscom_auth(cookie)


def extract_pychess_pgn(page_html: str) -> str:
    board_json = _extract_data_attribute(page_html, "data-board")
    board = json.loads(board_json)
    pgn = board.get("pgn")
    if not pgn:
        raise ValueError("Pychess page did not contain data-board PGN.")
    return pgn.replace("] [", "]\n[").replace("] 1.", "]\n\n1.")


def extract_pychess_game_id(value: str) -> str:
    match = re.search(r"(?:pychess\.org/)?([A-Za-z0-9_-]{8})(?:\b|$)", value)
    if not match:
        raise ValueError(f"Could not find pychess game id in {value!r}")
    return match.group(1)


def extract_pychess_game_ids(text: str) -> list[str]:
    ids = set(re.findall(r"data-gameid=['\"]([A-Za-z0-9_-]{8})['\"]", text))
    ids.update(re.findall(r"pychess\.org/([A-Za-z0-9_-]{8})", text))
    ids.update(re.findall(r'href=["\']/([A-Za-z0-9_-]{8})["\']', text))
    route_words = {"variants", "analysis", "bughouse", "crazyhou", "atomic96", "3check96"}
    return sorted(game_id for game_id in ids if game_id.lower() not in route_words)


def extract_chesscom_pgn4(page_html: str) -> str:
    # Guest chess.com pages currently render the variants app shell without game data.
    # Authenticated pages may expose PGN4 through app state; this parser is deliberately
    # narrow so a missing endpoint fails loudly instead of saving lossy standard PGN.
    for pattern in (r"StartFen4", r"\[Variant\s+\""):
        if re.search(pattern, page_html):
            start = page_html.find("[GameNr ")
            if start >= 0:
                return html.unescape(page_html[start:])
    raise ValueError(
        "Chess.com PGN4 was not present in the fetched page. "
        "Set CHESSCOM_COOKIE for authenticated WebSocket access, or use manual PGN4 export."
    )


def fetch_chesscom_pgn4_from_socket(
    game_id: str,
    cookie: str,
    timeout: int = 10,
    debug: bool = False,
    auth_user_id: int | None = None,
) -> str | None:
    user_context = fetch_chesscom_user_context(cookie, auth_user_id=auth_user_id)
    headers = [
        "Origin: https://www.chess.com",
        "User-Agent: Mozilla/5.0",
        f"Cookie: {cookie}",
    ]
    ws = websocket.create_connection("wss://variants.gcp-prod.chess.com", timeout=10, header=headers)
    try:
        window_id = "schess-puzzles"
        connect_data = {**user_context, "clientVersion": "0.0.0"}
        if debug:
            print(f"connect-user keys={sorted(connect_data.keys())}")
        ws.send(json.dumps({"action": "connect-user", "data": connect_data, "windowId": window_id}))
        game_join_sent = False
        import time

        deadline = time.monotonic() + timeout
        ignored_payloads = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ws.settimeout(remaining)
            raw = ws.recv()
            message = json.loads(raw)
            mutation = str(message.get("mutation", "")).lower()
            if debug:
                data = _decode_socket_data(message.get("data"))
                keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
                print(f"socket mutation={mutation!r} data_keys={keys}")
            if mutation == "user_connected" and not game_join_sent:
                ws.send(
                    json.dumps(
                        {
                            "action": "game",
                            "data": {"gameNr": int(game_id), "action": "join"},
                            "windowId": window_id,
                        }
                    )
                )
                game_join_sent = True
                if debug:
                    print(f"sent game join gameNr={game_id}")
            data = _decode_socket_data(message.get("data"))
            for pgn4 in _find_pgn4_candidates(data):
                headers = chesscom_pgn4_headers(pgn4)
                received_game_id = headers.get("GameNr")
                if received_game_id != str(game_id):
                    ignored_payloads += 1
                    if debug:
                        print(
                            "ignored PGN4 payload "
                            f"gameNr={received_game_id!r} variant={headers.get('Variant')!r}; "
                            f"expected gameNr={game_id}"
                        )
                    continue
                if debug and ignored_payloads:
                    print(f"matched requested PGN4 after ignoring {ignored_payloads} unrelated payload(s)")
                return pgn4
    except websocket.WebSocketTimeoutException:
        return None
    finally:
        ws.close()


def discover_chesscom_variant_archive(
    *,
    cookie: str,
    player_id: int | None = None,
    username: str | None = None,
    days: str = "0-9999",
    game_type: str = "",
    rating_type: str = "",
    title: str = "seirawan",
    start_page: int = 0,
    limit_pages: int = 1,
    archive_timeout: int = 5,
    debug: bool = False,
    auth_user_id: int | None = None,
) -> list[str]:
    user_context = fetch_chesscom_user_context(cookie, auth_user_id=auth_user_id)
    if not user_context.get("id"):
        raise ValueError("Could not read authenticated chess.com user context from cookie.")
    ws = _open_chesscom_variants_socket(cookie)
    try:
        window_id = "schess-puzzles"
        _send_socket(ws, "connect-user", {**user_context, "clientVersion": "0.0.0"}, window_id)
        connected = _wait_for_socket_mutation(ws, "user_connected", debug=debug)
        if connected is None:
            raise ValueError("Chess.com variants socket did not confirm user_connected.")
        if player_id is None and username:
            player_id = _resolve_chesscom_variant_player_id(ws, username, window_id, debug=debug)
            if debug:
                print(f"resolved username={username!r} player_id={player_id!r}")
        if player_id is None and not title:
            raise ValueError("discover archive requires --player-id, a resolvable --username, or --title for global search")

        game_ids: list[str] = []
        for page in range(start_page, start_page + max(1, limit_pages)):
            query_id = int(__import__("time").time() * 1000)
            params = {
                "days": days,
                "playerId": player_id if player_id is not None else "",
                "gameType": game_type,
                "gameNr": "",
                "ratingType": rating_type,
                "title": title,
                "q": {"ruleVariants": {"seirawanSetup": True}},
                "page": page,
                "queryId": query_id,
            }
            if debug:
                print(f"archive search params={params}")
            _send_socket(ws, "search-archive", params, window_id)
            got_archive_result = False
            for message in _read_socket_messages(ws, timeout=archive_timeout):
                mutation = str(message.get("mutation", "")).lower()
                data = _decode_socket_data(message.get("data"))
                if debug:
                    keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
                    print(f"archive mutation={mutation!r} data_keys={keys}")
                if mutation in {"add_games_search_result", "set_games_search_result"} and isinstance(data, dict):
                    games = data.get("games", [])
                    if debug:
                        print(
                            "archive result "
                            f"games={len(games)} "
                            f"lastPage={data.get('lastPage')!r}"
                        )
                        for index, game in enumerate(games[:3], start=1):
                            if isinstance(game, dict):
                                sample = {
                                    key: game.get(key)
                                    for key in (
                                        "gameNr",
                                        "title",
                                        "name",
                                        "gameType",
                                        "ratingType",
                                        "variant",
                                        "ruleVariants",
                                        "q",
                                        "white",
                                        "black",
                                    )
                                    if key in game
                                }
                                print(f"archive sample {index}: keys={sorted(game.keys())} values={sample}")
                    accepted_games = [
                        game
                        for game in games
                        if isinstance(game, dict) and is_chesscom_official_seirawan_archive_game(game)
                    ]
                    if debug and len(accepted_games) != len(games):
                        print(
                            "archive filter "
                            f"accepted={len(accepted_games)} rejected_mixed_or_nonstandard="
                            f"{len(games) - len(accepted_games)}"
                        )
                    for game in accepted_games:
                        game_nr = game.get("gameNr")
                        if game_nr is not None:
                            game_ids.append(str(game_nr))
                    got_archive_result = True
                    if data.get("lastPage"):
                        return _unique_preserve_order(game_ids)
                    break
            if not got_archive_result:
                raise ValueError(
                    f"Chess.com archive page {page} did not return a search result within {archive_timeout}s"
                )
        return _unique_preserve_order(game_ids)
    finally:
        ws.close()


_OFFICIAL_SEIRAWAN_RULE_KEYS = frozenset({"enpassant", "play4mate", "promoteto", "seirawansetup"})
_OFFICIAL_SEIRAWAN_RULE_TOKENS = frozenset({"enpassant", "play4mate", "promoteto=behnqr", "seirawansetup"})


def is_chesscom_official_seirawan_archive_game(game: dict) -> bool:
    """Keep Chess.com's official Seirawan queue, excluding mixed custom variants."""
    queue = game.get("q")
    if not isinstance(queue, dict):
        return False
    rules = queue.get("ruleVariants")
    if not isinstance(rules, dict):
        return False
    rule_keys = frozenset(str(key).lower() for key in rules)
    return (
        queue.get("title") == "Seirawan Chess"
        and queue.get("variantUrl") == "seirawan-chess"
        and queue.get("twoPlayerWhiteVsBlack") is True
        and queue.get("eightByEight") is True
        and rule_keys == _OFFICIAL_SEIRAWAN_RULE_KEYS
        and rules.get("seirawanSetup") is True
    )


def is_chesscom_official_seirawan_rules(value: str) -> bool:
    return frozenset(value.lower().split()) == _OFFICIAL_SEIRAWAN_RULE_TOKENS

def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered

def _resolve_chesscom_variant_player_id(ws, username: str, window_id: str, debug: bool = False) -> int | None:
    _send_socket(ws, "autocomplete-username", {"username": username, "gameType": "", "queryType": "games"}, window_id)
    for message in _read_socket_messages(ws, timeout=10):
        mutation = str(message.get("mutation", "")).lower()
        data = _decode_socket_data(message.get("data"))
        if debug:
            keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
            print(f"autocomplete mutation={mutation!r} data_keys={keys}")
        if mutation in {"set_username_choices", "username_choices"} and isinstance(data, dict):
            for player in data.get("players", []):
                if player.get("username", "").lower() == username.lower():
                    return int(player["uid"])
        if isinstance(data, dict):
            for player in data.get("players", []):
                if isinstance(player, dict) and player.get("username", "").lower() == username.lower():
                    return int(player["uid"])
    return None


def _wait_for_socket_mutation(ws, target: str, timeout: int = 15, debug: bool = False) -> object | None:
    target = target.lower()
    for message in _read_socket_messages(ws, timeout=timeout):
        mutation = str(message.get("mutation", "")).lower()
        data = _decode_socket_data(message.get("data"))
        if debug:
            keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
            print(f"connect mutation={mutation!r} data_keys={keys}")
        if mutation == target:
            return data
    return None


def _open_chesscom_variants_socket(cookie: str):
    return websocket.create_connection(
        "wss://variants.gcp-prod.chess.com",
        timeout=10,
        header=[
            "Origin: https://www.chess.com",
            "User-Agent: Mozilla/5.0",
            f"Cookie: {cookie}",
        ],
    )


def fetch_chesscom_user_context(cookie: str, auth_user_id: int | None = None) -> dict:
    response = _fetch_chesscom_variants_page(cookie)
    response.raise_for_status()
    context = _extract_chesscom_context(response.text)
    user = context.get("user") or {}
    if isinstance(user, dict) and user.get("id"):
        return user
    return _access_token_user_context(cookie, auth_user_id)



def _access_token_user_context(cookie: str, auth_user_id: int | None) -> dict:
    if auth_user_id is None:
        return {}
    token = _cookie_value(cookie, "ACCESS_TOKEN")
    if not token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        payload = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return {}
    uuid = claims.get("sub")
    if not uuid:
        return {}
    return {"id": int(auth_user_id), "uuid": uuid}


def _cookie_value(cookie: str, name: str) -> str | None:
    for part in cookie.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value.strip().strip('"').strip("'")
    return None

def inspect_chesscom_auth(cookie: str) -> dict:
    response = _fetch_chesscom_variants_page(cookie)
    context = _extract_chesscom_context(response.text)
    user = context.get("user") if isinstance(context, dict) else None
    text = response.text
    cookie_names = _cookie_names(cookie)
    return {
        "cookie_length": len(cookie),
        "cookie_names": cookie_names,
        "has_access_token_cookie": "ACCESS_TOKEN" in cookie_names,
        "has_session_cookie": any(name.lower() in {"sessionid", "phpcc", "chesscom_session"} for name in cookie_names),
        "status_code": response.status_code,
        "final_url": response.url,
        "content_type": response.headers.get("content-type", ""),
        "html_length": len(text),
        "has_context_marker": "context = " in text,
        "has_user_marker": '"user"' in text or "'user'" in text,
        "has_login_text": "Log In" in text or "login" in response.url.lower(),
        "has_cloudflare_text": "Cloudflare" in text or "cf-chl" in text,
        "context_keys": sorted(context.keys()) if isinstance(context, dict) else [],
        "user_keys": sorted(user.keys()) if isinstance(user, dict) else [],
        "username": user.get("username") if isinstance(user, dict) else None,
        "user_id": user.get("id") if isinstance(user, dict) else None,
    }


def _cookie_names(cookie: str) -> list[str]:
    names = []
    for part in cookie.split(";"):
        name, _, _value = part.strip().partition("=")
        if name:
            names.append(name)
    return sorted(set(names))


def _fetch_chesscom_variants_page(cookie: str):
    return requests.get(
        "https://www.chess.com/variants",
        timeout=30,
        headers={**_headers(), "Cookie": cookie},
    )


def _extract_chesscom_context(page_html: str) -> dict:
    marker = "context = "
    start = page_html.find(marker)
    if start < 0:
        return {}
    start += len(marker)
    end = _find_balanced_json_end(page_html, start)
    if end is None:
        return {}
    try:
        return json.loads(page_html[start:end])
    except json.JSONDecodeError:
        return {}


def _find_balanced_json_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _send_socket(ws, action: str, data: dict, window_id: str) -> None:
    ws.send(json.dumps({"action": action, "data": data, "windowId": window_id}))


def _read_socket_messages(ws, timeout: int):
    """Yield messages until an absolute deadline, not merely an idle timeout."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            # The variants service emits pings while a request is stalled. A
            # fixed socket timeout would therefore never expire in that case.
            ws.settimeout(remaining)
            raw = ws.recv()
            if not isinstance(raw, str) or not raw.strip():
                continue
            yield json.loads(raw)
        except websocket.WebSocketTimeoutException:
            return
        except json.JSONDecodeError:
            continue


def _decode_socket_data(data: object) -> object:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data
    return data


def chesscom_pgn4_headers(pgn4: str) -> dict[str, str]:
    # StartFen4 spans many physical lines, so header values must be parsed in
    # DOTALL mode rather than line-by-line.
    return {
        key: value
        for key, value in re.findall(r'^\[([^\s]+)\s+"(.*?)"\]$', pgn4, flags=re.MULTILINE | re.DOTALL)
    }


def validate_chesscom_seirawan_pgn4(pgn4: str, *, expected_game_id: str) -> tuple[bool, str]:
    """Validate Chess.com's two-player Seirawan PGN4 wrapper.

    Chess.com labels this shared four-player protocol wrapper as ``Variant FFA``
    even for its official two-player Seirawan queue. The real variant identity
    therefore lives in RuleVariants and the embedded white-vs-black setup.
    """
    headers = chesscom_pgn4_headers(pgn4)
    if headers.get("GameNr") != str(expected_game_id):
        return False, f"GameNr was {headers.get('GameNr')!r}, not {expected_game_id!r}"

    rules = headers.get("RuleVariants", "").lower()
    start_fen4 = headers.get("StartFen4", "")
    site = headers.get("Site", "").lower()
    if not is_chesscom_official_seirawan_rules(headers.get("RuleVariants", "")):
        return False, "RuleVariants was not the official Seirawan rule set"
    if "'wb':true" not in start_fen4.replace(" ", "").lower():
        return False, "StartFen4 was not a two-player white-vs-black board"
    if "/variants/seirawan-chess/" not in site:
        return False, f"Site was not a Seirawan Chess game URL: {headers.get('Site')!r}"
    return True, ""

def _find_pgn4_candidates(value: object) -> list[str]:
    candidates: list[str] = []
    if isinstance(value, dict):
        pgn4 = value.get("pgn4")
        if isinstance(pgn4, str) and "StartFen4" in pgn4:
            candidates.append(pgn4)
        for child in value.values():
            candidates.extend(_find_pgn4_candidates(child))
    elif isinstance(value, list):
        for child in value:
            candidates.extend(_find_pgn4_candidates(child))
    return candidates


def extract_chesscom_variant_game_id(value: str) -> str:
    match = re.search(r"(?:variants/.+?/game/|variants/game/|GameNr\s+\")(\d+)", value)
    if not match:
        match = re.search(r"\b(\d{6,})\b", value)
    if not match:
        raise ValueError(f"Could not find chess.com variant game id in {value!r}")
    return match.group(1)


def extract_chesscom_variant_game_ids(text: str) -> list[str]:
    ids = set(re.findall(r"variants/[^/]+/game/(\d+)", text))
    ids.update(re.findall(r"variants/game/(\d+)", text))
    ids.update(re.findall(r'\[GameNr\s+"(\d+)"\]', text))
    return sorted(ids)


def _extract_data_attribute(page_html: str, name: str) -> str:
    match = re.search(rf'{name}="([^"]+)"', page_html)
    if not match:
        raise ValueError(f"Could not find {name} in page HTML.")
    return html.unescape(match.group(1))


def _headers() -> dict[str, str]:
    return {"User-Agent": "SChessPuzzles/0.1 (+local research tool)"}
