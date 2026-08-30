"""Variant-aware, engine-free approximations of human candidate ordering.

The functions here deliberately use only legal moves and the resulting FEN.  That
makes the feature definitions usable for ordinary chess and Seirawan chess,
including gating moves, en passant, and Chess960 castling encodings.
"""
from __future__ import annotations

import math
from collections import Counter

import pyffish


VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "H": 7, "E": 7, "K": 99}
KNIGHT = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-1, 2), (-2, 1))
KING = ((1, 1), (1, 0), (1, -1), (0, 1), (0, -1), (-1, 1), (-1, 0), (-1, -1))
MAX_REFUTATION_CANDIDATES = 6


def board_from_fen(fen: str) -> dict[str, str]:
    board: dict[str, str] = {}
    for row, encoded in enumerate(fen.split()[0].split("[")[0].split("/")):
        file_index = 0
        for char in encoded:
            if char.isdigit():
                file_index += int(char)
            else:
                board[f"{chr(97 + file_index)}{8 - row}"] = char
                file_index += 1
    return board


def _square(file_index: int, rank_index: int) -> str | None:
    if not (0 <= file_index < 8 and 0 <= rank_index < 8):
        return None
    return f"{chr(97 + file_index)}{rank_index + 1}"


def _xy(square: str) -> tuple[int, int]:
    return ord(square[0]) - 97, int(square[1]) - 1


def _ray(board: dict[str, str], origin: str, directions: tuple[tuple[int, int], ...]) -> set[str]:
    file_index, rank_index = _xy(origin)
    result: set[str] = set()
    for dx, dy in directions:
        x, y = file_index + dx, rank_index + dy
        while target := _square(x, y):
            result.add(target)
            if target in board:
                break
            x, y = x + dx, y + dy
    return result


def attacks(board: dict[str, str], origin: str) -> set[str]:
    piece = board[origin]
    kind = piece.upper()
    file_index, rank_index = _xy(origin)
    if kind == "P":
        step = 1 if piece.isupper() else -1
        return {
            target
            for dx in (-1, 1)
            if (target := _square(file_index + dx, rank_index + step)) is not None
        }
    result = {
        target
        for dx, dy in KNIGHT
        if kind in {"N", "H", "E"}
        and (target := _square(file_index + dx, rank_index + dy)) is not None
    }
    if kind in {"B", "Q", "H"}:
        result |= _ray(board, origin, ((1, 1), (1, -1), (-1, 1), (-1, -1)))
    if kind in {"R", "Q", "E"}:
        result |= _ray(board, origin, ((1, 0), (-1, 0), (0, 1), (0, -1)))
    if kind == "K":
        result |= {
            target
            for dx, dy in KING
            if (target := _square(file_index + dx, rank_index + dy)) is not None
        }
    return result


def attack_map(board: dict[str, str], white: bool) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for origin, piece in board.items():
        if piece.isupper() != white:
            continue
        for target in attacks(board, origin):
            result.setdefault(target, []).append(origin)
    return result


def material(board: dict[str, str], white: bool) -> int:
    return sum(VALUES.get(piece.upper(), 0) for piece in board.values() if piece.isupper() == white and piece.upper() != "K")


def _new_material_threat(before: dict[str, str], after: dict[str, str], mover_white: bool) -> int:
    """Largest newly-created or reinforced material threat in pawn units."""
    before_attacks = attack_map(before, mover_white)
    after_attacks = attack_map(after, mover_white)
    defenders = attack_map(after, not mover_white)
    gains: list[int] = []
    for target, victim in after.items():
        if victim.isupper() == mover_white or victim.upper() == "K":
            continue
        before_count = len(before_attacks.get(target, []))
        after_count = len(after_attacks.get(target, []))
        defender_count = len(defenders.get(target, []))
        # A second attacker can convert an already-attacked, defended piece.
        if after_count <= before_count or after_count <= defender_count:
            continue
        victim_value = VALUES.get(victim.upper(), 0)
        cheapest_attacker = min(VALUES.get(after[source].upper(), 0) for source in after_attacks[target])
        gains.append(victim_value if defender_count == 0 else max(0, victim_value - cheapest_attacker))
    return max(gains, default=0)

def _hanging_moved_piece(after: dict[str, str], move: str, mover_white: bool, legal_replies: list[str]) -> int:
    """Material genuinely at risk from a *legal* immediate capture.

    Static attack maps intentionally overapproximate attacks. In particular, a
    pinned Elephant may geometrically attack a rook while being unable to take
    it. Candidate preference must use legal replies here.
    """
    target = move[2:4]
    moved_piece = after.get(target)
    if not moved_piece or moved_piece.isupper() != mover_white or moved_piece.upper() == "K":
        return 0
    if not any(reply[2:4] == target for reply in legal_replies):
        return 0
    piece_value = VALUES.get(moved_piece.upper(), 0)
    own_defenders = attack_map(after, mover_white)
    if target not in own_defenders:
        return piece_value
    return max(0, piece_value - min(VALUES.get(after.get(reply[:2], "P").upper(), 0) for reply in legal_replies if reply[2:4] == target))

def candidate_features(variant: str, fen: str, move: str, parent_legal_count: int | None = None) -> dict[str, float | int | bool | str]:
    """Return human-ordering signals for one legal move.

    ``forcing_level`` is intentionally coarse: check-capture, check, capture,
    material threat, quiet.  The softer ``attractiveness`` retains material,
    simplification and safety information without allowing a quiet move to leap
    ahead of a forcing move merely through numeric scale.
    """
    before = board_from_fen(fen)
    mover_white = fen.split()[1] == "w"
    after_fen = pyffish.get_fen(variant, fen, [move])
    after = board_from_fen(after_fen)
    captured_value = max(0, material(before, not mover_white) - material(after, not mover_white))
    own_material_delta = material(after, mover_white) - material(before, mover_white)
    simplification = max(0, sum(VALUES.get(piece.upper(), 0) for piece in before.values() if piece.upper() != "K") - sum(VALUES.get(piece.upper(), 0) for piece in after.values() if piece.upper() != "K"))
    check = bool(pyffish.gives_check(variant, fen, [move]))
    threat_value = _new_material_threat(before, after, mover_white)
    forcing_level = 4 if check and captured_value else 3 if check else 2 if captured_value else 1 if threat_value else 0
    legal_replies = list(pyffish.legal_moves(variant, after_fen, []))
    opponent_reply_count = len(legal_replies)
    mobility_drop = (parent_legal_count if parent_legal_count is not None else len(pyffish.legal_moves(variant, fen, []))) - opponent_reply_count
    hanging_cost = _hanging_moved_piece(after, move, mover_white, legal_replies)

    # The discrete tier dominates. Values beneath it only order moves which a
    # player would consider in broadly the same candidate class.
    within_tier = (
        min(12, captured_value) * 1.25
        + min(12, threat_value) * 0.85
        + min(12, simplification) * 0.20
        + max(-8, min(8, mobility_drop)) * 0.08
        + max(-4, min(4, own_material_delta)) * 0.20
        - min(8, hanging_cost) * 0.95
    )
    priority = forcing_level * 100.0 + within_tier
    attractiveness = forcing_level * 1.35 + within_tier / 12.0
    return {
        "move": move,
        "forcing_level": forcing_level,
        "check": check,
        "captured_value": captured_value,
        "material_threat_value": threat_value,
        "simplification": simplification,
        "mobility_drop": mobility_drop,
        "hanging_cost": hanging_cost,
        "opponent_reply_count": opponent_reply_count,
        "priority": round(priority, 3),
        "attractiveness": round(attractiveness, 3),
    }


def _countercheck_attack_value(variant: str, fen: str, candidate: dict[str, float | int | bool | str]) -> int:
    """Value lost when a countercheck leaves no legal way to save the mover.

    A countercheck is only a refutation if every legal check evasion still lets
    the opponent capture the moved piece next. This avoids treating a harmless
    check as decisive merely because it geometrically attacks the mover.
    """
    move = str(candidate["move"])
    after_fen = pyffish.get_fen(variant, fen, [move])
    mover_white = fen.split()[1] == "w"
    target = move[2:4]
    highest = 0
    for reply in pyffish.legal_moves(variant, after_fen, []):
        if not pyffish.gives_check(variant, after_fen, [reply]):
            continue
        reply_fen = pyffish.get_fen(variant, after_fen, [reply])
        board = board_from_fen(reply_fen)
        threatened = board.get(target)
        attacker = reply[2:4]
        if not (
            threatened
            and threatened.isupper() == mover_white
            and attacker in board
            and target in attacks(board, attacker)
        ):
            continue
        evasions = list(pyffish.legal_moves(variant, reply_fen, []))
        if evasions and all(
            any(next_reply[2:4] == target for next_reply in pyffish.legal_moves(variant, pyffish.get_fen(variant, reply_fen, [evasion]), []))
            for evasion in evasions
        ):
            highest = max(highest, VALUES.get(threatened.upper(), 0))
    return highest

def rank_candidates(
    variant: str,
    fen: str,
    important_moves: tuple[str, ...] = (),
) -> list[dict[str, float | int | bool | str]]:
    legal_moves = list(pyffish.legal_moves(variant, fen, []))
    candidates = [candidate_features(variant, fen, move, len(legal_moves)) for move in legal_moves]
    preliminary = sorted(candidates, key=lambda item: (-float(item["priority"]), str(item["move"])))
    active_moves = {str(item["move"]) for item in preliminary[:MAX_REFUTATION_CANDIDATES]}
    active_moves.update(important_moves)
    # A candidate needs both a visible material threat and a place in the narrow
    # human attention band before we inspect counterchecks. Puzzle profiling can
    # add the known solution to this band without making generation depend on it.
    for candidate in candidates:
        if str(candidate["move"]) not in active_moves or int(candidate["forcing_level"]) != 1:
            continue
        candidate["countercheck_examined"] = True
        pressure = _countercheck_attack_value(variant, fen, candidate)
        if not pressure:
            continue
        candidate["countercheck_attack_value"] = pressure
        penalty = min(8, pressure) * 1.10
        candidate["priority"] = round(float(candidate["priority"]) - penalty, 3)
        candidate["attractiveness"] = round(float(candidate["attractiveness"]) - penalty / 12.0, 3)
    return sorted(candidates, key=lambda item: (-float(item["priority"]), str(item["move"])))

def distribution(candidates: list[dict[str, float | int | bool | str]], temperature: float = 1.0) -> dict[str, float]:
    if not candidates:
        return {}
    maximum = max(float(item["attractiveness"]) for item in candidates)
    weights = {
        str(item["move"]): math.exp((float(item["attractiveness"]) - maximum) / max(0.1, temperature))
        for item in candidates
    }
    total = sum(weights.values())
    return {move: weight / total for move, weight in weights.items()}


def entropy(probabilities: dict[str, float]) -> float:
    return -sum(value * math.log(value) for value in probabilities.values() if value > 0)


def candidate_summary(variant: str, fen: str, solution_move: str) -> dict[str, float | int | bool | list[dict]]:
    candidates = rank_candidates(variant, fen, (solution_move,))
    solution = next((item for item in candidates if item["move"] == solution_move), None)
    if solution is None:
        raise ValueError(f"solution {solution_move!r} is not legal in {fen!r}")
    probabilities = distribution(candidates)
    solution_index = next(index for index, item in enumerate(candidates, start=1) if item["move"] == solution_move)
    top = candidates[0]
    higher = sum(float(item["priority"]) > float(solution["priority"]) for item in candidates)
    equal = sum(float(item["priority"]) == float(solution["priority"]) for item in candidates)
    return {
        "solution_priority_rank": higher + 1,
        "solution_sorted_rank": solution_index,
        "solution_top_priority": solution["priority"] == top["priority"],
        "solution_priority_tier_size": equal,
        "solution_probability": probabilities[solution_move],
        "solution_gap_to_top1": probabilities[str(top["move"])] - probabilities[solution_move],
        "candidate_entropy": entropy(probabilities),
        "solution": solution,
        "top_candidate": top,
        "candidates": candidates[:12],
    }
