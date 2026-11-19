from __future__ import annotations

import re
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import pyffish


HEADER_RE = re.compile(r'^\[(\w+)\s+"(.*)"\]$', re.DOTALL)
MOVE_NUMBER_RE = re.compile(r"^\d+\.(?:\.\.)?$")
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
CHESSCOM_ARTIFACT_TOKENS = {"D", "P", "R", "S", "T"}
PGN4_MOVE_PREFIX_RE = re.compile(r"^(?P<number>\d+)\.(?P<black>\.)?")


@dataclass(frozen=True)
class ParsedGame:
    headers: dict[str, str]
    moves: list[str]


@dataclass(frozen=True)
class ParsedUciGame:
    headers: dict[str, str]
    variant: str
    start_fen: str
    moves: list[str]

@dataclass
class Pgn4Move:
    """A PGN4 move plus its alternative continuations."""

    token: str
    variations: list[list["Pgn4Move"]]


def write_epd_from_pgn(path: Path, stream: TextIO, configured_variant: str = "seirawan") -> None:
    for game in iter_uci_games(path, configured_variant):
        variant = game.variant
        start_fen = game.start_fen
        site = game.headers.get("Site", "")

        move_stack: list[str] = []
        _write_epd(stream, start_fen, variant, site, move_stack)

        for move in game.moves:
            move_stack.append(move)
            _write_epd(stream, start_fen, variant, site, move_stack)


def iter_uci_games(path: Path, configured_variant: str = "seirawan") -> list[ParsedUciGame]:
    games = parse_pgn(path)
    if any("StartFen4" in game.headers for game in games):
        return [_pgn4_to_uci_game(game, configured_variant) for game in games]

    parsed: list[ParsedUciGame] = []
    for game in games:
        variant = _normalize_variant(game.headers.get("Variant", configured_variant))
        start_fen = game.headers.get("FEN") or pyffish.start_fen(variant)
        if game.headers.get("UciMoves"):
            parsed.append(ParsedUciGame(game.headers, variant, start_fen, game.headers["UciMoves"].split()))
            continue
        moves: list[str] = []
        for san in game.moves:
            moves.append(san_to_uci(variant, start_fen, moves, san))
        parsed.append(ParsedUciGame(game.headers, variant, start_fen, moves))
    return parsed


def parse_pgn(path: Path) -> list[ParsedGame]:
    text = path.read_text(encoding="utf-8-sig")
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n(?=\[Event\s+\")", text) if chunk.strip()]
    return [_parse_game(chunk) for chunk in chunks]


def read_headers(path: Path) -> list[dict[str, str]]:
    return [game.headers for game in parse_pgn(path)]

def pgn4_to_pychess_pgn(text: str) -> str:
    """Convert Chess.com's two-player Seirawan PGN4 to importable PyChess PGN.

    Unlike the analysis parser above, this preserves recursive PGN4 variations.
    Chess.com writes them after the move whose continuation they replace, which
    maps directly to PGN recursive annotation variations.
    """

    games = _parse_pgn4_text(text)
    if not games:
        raise ValueError("No PGN4 game found.")
    return "\n\n".join(_render_pychess_game(headers, moves) for headers, moves in games) + "\n"


def san_to_uci(variant: str, start_fen: str, move_stack: list[str], san: str) -> str:
    wanted = _normalize_san(san)
    legal_moves = pyffish.legal_moves(variant, start_fen, move_stack)

    for move in legal_moves:
        generated = pyffish.get_san_moves(variant, start_fen, [*move_stack, move])[-1]
        if _normalize_san(generated) == wanted:
            return move

    raise ValueError(f"Could not resolve SAN move {san!r} after moves {move_stack!r}")


def _parse_game(chunk: str) -> ParsedGame:
    headers: dict[str, str] = {}
    movetext_lines: list[str] = []

    for line in _join_multiline_headers(chunk.splitlines()):
        line = line.strip()
        match = HEADER_RE.match(line)
        if match:
            headers[match.group(1)] = match.group(2)
        elif line:
            movetext_lines.append(line)

    return ParsedGame(headers=headers, moves=_tokenize_movetext(" ".join(movetext_lines)))


def _join_multiline_headers(lines: list[str]) -> list[str]:
    joined: list[str] = []
    buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        if buffer:
            buffer.append(line)
            if stripped.endswith('"]'):
                joined.append("\n".join(buffer))
                buffer = []
            continue
        if stripped.startswith("[") and not HEADER_RE.match(stripped):
            buffer = [line]
            if stripped.endswith('"]'):
                joined.append("\n".join(buffer))
                buffer = []
            continue
        joined.append(line)
    if buffer:
        joined.extend(buffer)
    return joined


def _tokenize_movetext(text: str) -> list[str]:
    text = re.sub(r"\{[^}]*\}", " ", text)
    text = re.sub(r";[^\n]*", " ", text)
    text = re.sub(r"\([^)]*\)", " ", text)

    moves: list[str] = []
    for token in text.split():
        token = token.strip()
        if not token or token in RESULTS:
            continue
        if token == "..":
            continue
        token = re.sub(r"^\d+\.(?:\.\.)?", "", token)
        if not token or MOVE_NUMBER_RE.match(token) or token in RESULTS:
            continue
        if token in CHESSCOM_ARTIFACT_TOKENS:
            continue
        moves.append(token)
    return moves


def _pgn4_to_uci_game(game: ParsedGame, configured_variant: str) -> ParsedUciGame:
    variant = _normalize_variant(game.headers.get("RuleVariants", configured_variant))
    start_fen = pyffish.start_fen(variant)
    moves = [_pgn4_move_to_uci(move, "w" if index % 2 == 0 else "b") for index, move in enumerate(game.moves)]
    return ParsedUciGame(game.headers, variant, start_fen, moves)


def _pgn4_move_to_uci(token: str, side: str = "w") -> str:
    token = token.rstrip("+#").replace("+&@", "&@").replace("#&@", "&@")
    move_part, _, gate_part = token.partition("&@")
    gate_suffix = _pgn4_gate_suffix(gate_part)

    if move_part in {"O-O", "O-O-O"}:
        return _pgn4_castle_to_uci(move_part, gate_part, gate_suffix, side)

    coords = re.findall(r"[a-z]\d+", move_part)
    if len(coords) < 2:
        raise ValueError(f"Unsupported PGN4 move token: {token}")
    promotion_suffix = _pgn4_promotion_suffix(move_part)
    if promotion_suffix and gate_suffix:
        raise ValueError(f"Unsupported PGN4 move with promotion and gate: {token}")
    return _pgn4_square(coords[0]) + _pgn4_square(coords[-1]) + promotion_suffix + gate_suffix


def _pgn4_promotion_suffix(move_part: str) -> str:
    match = re.search(r"=([BEHNQR])$", move_part)
    return match.group(1).lower() if match else ""


def _pgn4_gate_suffix(gate_part: str) -> str:
    if not gate_part:
        return ""
    match = re.match(r"[ry]([EH])-", gate_part)
    if not match:
        raise ValueError(f"Unsupported PGN4 gate token: {gate_part}")
    return match.group(1).lower()


def _pgn4_castle_to_uci(move_part: str, gate_part: str, gate_suffix: str, side: str) -> str:
    home_rank = "1" if side == "w" else "8"
    if not gate_suffix:
        return f"e{home_rank}g{home_rank}" if move_part == "O-O" else f"e{home_rank}c{home_rank}"

    gate_square = _pgn4_square(gate_part.rsplit("-", 1)[-1])
    king_from = f"e{home_rank}"
    king_side_rook_from = f"h{home_rank}"
    queen_side_rook_from = f"a{home_rank}"
    if move_part == "O-O":
        return (f"{king_side_rook_from}{king_from}" if gate_square == king_side_rook_from else f"{king_from}g{home_rank}") + gate_suffix
    return (f"{queen_side_rook_from}{king_from}" if gate_square == queen_side_rook_from else f"{king_from}c{home_rank}") + gate_suffix


def _pgn4_square(square: str) -> str:
    file_char = square[0]
    rank = int(square[1:])
    file_index = ord(file_char) - ord("d")
    board_rank = rank - 3
    if not 0 <= file_index < 8 or not 1 <= board_rank <= 8:
        raise ValueError(f"PGN4 square outside embedded 8x8 board: {square}")
    return f"{chr(ord('a') + file_index)}{board_rank}"


def _normalize_variant(value: str) -> str:
    normalized = value.lower().replace("-", "").replace("_", "")
    if "seirawan" in normalized or normalized in {"schess", "s-chess"}:
        return "seirawan"
    return value.lower()


def _normalize_san(san: str) -> str:
    san = san.strip()
    san = san.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    san = san.rstrip("+#")
    return san


def _write_epd(stream: TextIO, start_fen: str, variant: str, site: str, move_stack: list[str]) -> None:
    fen = pyffish.get_fen(variant, start_fen, move_stack)
    stream.write(f"{fen};variant {variant};site {site}\n")


def _parse_pgn4_text(text: str) -> list[tuple[dict[str, str], list[Pgn4Move]]]:
    """Parse PGN4 headers and a recursive move tree without losing variations."""

    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n(?=\[(?:GameNr|Event)\s+\")", text) if chunk.strip()]
    games: list[tuple[dict[str, str], list[Pgn4Move]]] = []
    for chunk in chunks:
        headers: dict[str, str] = {}
        movetext_lines: list[str] = []
        for line in _join_multiline_headers(chunk.splitlines()):
            stripped = line.strip()
            match = HEADER_RE.match(stripped)
            if match:
                headers[match.group(1)] = match.group(2)
            elif stripped:
                movetext_lines.append(stripped)
        if headers or movetext_lines:
            games.append((headers, _parse_pgn4_move_tree(" ".join(movetext_lines))))
    return games


def _parse_pgn4_move_tree(text: str) -> list[Pgn4Move]:
    text = re.sub(r"\{[^}]*\}", " ", text)
    text = re.sub(r";[^\n]*", " ", text)
    tokens = re.findall(r"\(|\)|[^\s()]+", text)
    index = 0

    def parse_sequence() -> list[Pgn4Move]:
        nonlocal index
        moves: list[Pgn4Move] = []
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if token == ")":
                break
            if token == "(":
                variation = parse_sequence()
                if moves and variation:
                    moves[-1].variations.append(variation)
                continue
            move = _clean_pgn4_movetext_token(token)
            if move:
                moves.append(Pgn4Move(move, []))
        return moves

    return parse_sequence()


def _clean_pgn4_movetext_token(token: str) -> str:
    if token in RESULTS or token == ".." or MOVE_NUMBER_RE.match(token):
        return ""
    token = re.sub(r"^\d+\.(?:\.)?", "", token)
    if not token or token in RESULTS or token in CHESSCOM_ARTIFACT_TOKENS:
        return ""
    return token


def _render_pychess_game(headers: dict[str, str], moves: list[Pgn4Move]) -> str:
    variant = _normalize_variant(headers.get("RuleVariants", headers.get("Variant", "seirawan")))
    if variant != "seirawan":
        raise ValueError(f"Only two-player Seirawan PGN4 is supported, got variant {variant!r}.")
    if "StartFen4" not in headers:
        raise ValueError("This does not look like a Chess.com PGN4 export (StartFen4 is missing).")

    start_fen = pyffish.start_fen(variant)
    result = headers.get("Result", "*")
    if result not in RESULTS:
        result = "*"

    output_headers = [
        ("Event", "Chess.com Seirawan Chess"),
        ("Site", _clean_site(headers.get("Site", ""))),
        ("Date", _pgn_date(headers.get("Date", ""))),
        ("Round", headers.get("GameNr", "?")),
        ("White", headers.get("White", "?")),
        ("Black", headers.get("Black", "?")),
        ("Result", result),
        ("Variant", "seirawan"),
        ("SetUp", "1"),
        ("FEN", start_fen),
    ]
    for name in ("WhiteElo", "BlackElo", "TimeControl", "Termination"):
        if headers.get(name):
            output_headers.append((name, headers[name]))

    rendered = _render_pgn4_sequence(variant, start_fen, [], moves)
    header_text = "\n".join(f'[{name} "{_escape_pgn_header(value)}"]' for name, value in output_headers)
    return f"{header_text}\n\n{rendered} {result}".rstrip()


def _render_pgn4_sequence(
    variant: str,
    start_fen: str,
    history: list[str],
    moves: list[Pgn4Move],
) -> str:
    rendered: list[str] = []
    current_history = list(history)
    for node in moves:
        before = list(current_history)
        uci = _pgn4_move_to_uci(node.token, _side_to_move(variant, start_fen, current_history))
        legal = pyffish.legal_moves(variant, start_fen, current_history)
        if uci not in legal:
            raise ValueError(f"PGN4 move {node.token!r} became {uci!r}, which is not legal after {current_history!r}.")
        san = pyffish.get_san_moves(variant, start_fen, [*current_history, uci])[-1]
        rendered.append(_pgn_move_prefix(variant, start_fen, current_history) + san)
        current_history.append(uci)

        for variation in node.variations:
            try:
                variation_text = _render_pgn4_sequence(variant, start_fen, current_history, variation)
            except ValueError as after_error:
                try:
                    variation_text = _render_pgn4_sequence(variant, start_fen, before, variation)
                except ValueError:
                    raise after_error
            rendered.append(f"({variation_text})")
    return " ".join(rendered)


def _side_to_move(variant: str, start_fen: str, history: list[str]) -> str:
    return pyffish.get_fen(variant, start_fen, history).split()[1]


def _pgn_move_prefix(variant: str, start_fen: str, history: list[str]) -> str:
    fields = pyffish.get_fen(variant, start_fen, history).split()
    return f"{fields[5]}. " if fields[1] == "w" else f"{fields[5]}... "


def _clean_site(value: str) -> str:
    match = re.search(r"https?://[^)\s\]]+", value)
    return match.group(0) if match else (value or "?")


def _pgn_date(value: str) -> str:
    match = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{4})\b", value)
    if not match:
        return "????.??.??"
    try:
        return datetime.strptime(" ".join(match.groups()), "%b %d %Y").strftime("%Y.%m.%d")
    except ValueError:
        return "????.??.??"


def _escape_pgn_header(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
