from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import pyffish


HEADER_RE = re.compile(r'^\[(\w+)\s+"(.*)"\]$', re.DOTALL)
MOVE_NUMBER_RE = re.compile(r"^\d+\.(?:\.\.)?$")
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
CHESSCOM_ARTIFACT_TOKENS = {"D", "P", "R", "T"}


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
