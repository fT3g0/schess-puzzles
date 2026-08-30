"""Add static forcingness and material/mate-threat signals to a move report."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pyffish

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "H": 7, "E": 7, "K": 99}
KNIGHT = ((1,2),(2,1),(2,-1),(1,-2),(-1,-2),(-2,-1),(-2,1),(-1,2))
KING = ((1,1),(1,0),(1,-1),(0,1),(0,-1),(-1,1),(-1,0),(-1,-1))


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/complexity/lichess_move_difficulty_200.json"))
    parser.add_argument("--output", type=Path, default=Path("data/complexity/lichess_move_difficulty_threat_200.json"))
    parser.add_argument("--mate-threats", action="store_true", help="Probe mate-in-one potential after the actual solution only.")
    return parser.parse_args()


def square(file: int, rank: int) -> str | None:
    return f"{chr(97 + file)}{rank + 1}" if 0 <= file < 8 and 0 <= rank < 8 else None


def xy(name: str) -> tuple[int, int]: return ord(name[0]) - 97, int(name[1]) - 1


def board_from_fen(fen: str) -> dict[str, str]:
    board = {}
    for row, encoded in enumerate(fen.split()[0].split("[")[0].split("/")):
        file = 0
        for char in encoded:
            if char.isdigit(): file += int(char)
            else: board[f"{chr(97 + file)}{8 - row}"] = char; file += 1
    return board


def ray(board: dict[str, str], origin: str, directions: tuple[tuple[int,int], ...]) -> set[str]:
    file, rank = xy(origin); result = set()
    for dx, dy in directions:
        x, y = file + dx, rank + dy
        while (target := square(x, y)):
            result.add(target)
            if target in board: break
            x += dx; y += dy
    return result


def attacks(board: dict[str, str], origin: str) -> set[str]:
    piece = board[origin]; kind = piece.upper(); file, rank = xy(origin)
    if kind == "P":
        step = 1 if piece.isupper() else -1
        return {target for dx in (-1,1) if (target := square(file + dx, rank + step))}
    result = {target for dx,dy in KNIGHT if kind in {"N","H","E"} and (target := square(file + dx, rank + dy))}
    if kind in {"B","Q","H"}: result |= ray(board, origin, ((1,1),(1,-1),(-1,1),(-1,-1)))
    if kind in {"R","Q","E"}: result |= ray(board, origin, ((1,0),(-1,0),(0,1),(0,-1)))
    if kind == "K": result |= {target for dx,dy in KING if (target := square(file + dx, rank + dy))}
    return result


def attack_map(board: dict[str, str], white: bool) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for origin, piece in board.items():
        if piece.isupper() == white:
            for target in attacks(board, origin): result.setdefault(target, []).append(origin)
    return result


def apply_standard_move(board: dict[str, str], fen: str, move: str) -> dict[str, str]:
    after = dict(board); source, target = move[:2], move[2:4]; piece = after.pop(source)
    file_from, rank_from = xy(source); file_to, rank_to = xy(target)
    fields = fen.split(); ep = fields[3] if len(fields) > 3 else "-"
    if piece.upper() == "P" and target == ep and target not in after and file_from != file_to:
        after.pop(f"{target[0]}{rank_from + 1}", None)
    if piece.upper() == "K" and abs(file_to - file_from) == 2:
        rook_from, rook_to = ("h" + source[1], "f" + source[1]) if file_to > file_from else ("a" + source[1], "d" + source[1])
        if rook_from in after: after[rook_to] = after.pop(rook_from)
    if len(move) == 5 and move[-1].lower() in {"q","r","b","n"}:
        piece = move[-1].upper() if piece.isupper() else move[-1].lower()
    after[target] = piece
    return after


def material_gain(before: dict[str, str], after: dict[str, str], white: bool) -> int:
    before_attacks, after_attacks = attack_map(before, white), attack_map(after, white)
    defenders = attack_map(after, not white); gains = []
    for target, piece in after.items():
        if piece.isupper() == white or piece.upper() == "K" or target in before_attacks or target not in after_attacks: continue
        victim = VALUES.get(piece.upper(), 0)
        attacker = min(VALUES.get(after[source].upper(), 0) for source in after_attacks[target])
        gains.append(victim if target not in defenders else max(0, victim - attacker))
    return max(gains, default=0)


def captured_value(board: dict[str, str], fen: str, move: str) -> int:
    source, target = move[:2], move[2:4]
    if target in board:
        return VALUES.get(board[target].upper(), 0)
    if board[source].upper() == "P" and target == fen.split()[3] and source[0] != target[0]:
        return 1
    return 0


def move_features(fen: str, board: dict[str, str], move: str, white: bool) -> dict:
    after_board = apply_standard_move(board, fen, move)
    enemy_king = next((name for name, piece in after_board.items() if piece.upper() == "K" and piece.isupper() != white), "")
    check = bool(enemy_king and enemy_king in attack_map(after_board, white))
    source, target = move[:2], move[2:4]
    capture = captured_value(board, fen, move) > 0
    threat = material_gain(board, after_board, white)
    level = 4 if check and capture else 3 if check else 2 if capture else 1 if threat else 0
    return {"level": level, "material_threat_value": threat, "captured_value": captured_value(board, fen, move), "after_board": after_board}


def immediately_refuted(after_fen: str, move: str, moved_piece_value: int, captured: int) -> bool:
    """Whether the moved piece can be legally captured at a clear material loss."""
    target = move[2:4]
    return moved_piece_value - captured >= 2 and any(reply[2:4] == target for reply in pyffish.legal_moves("chess", after_fen, []))


def mate_after_pass(fen: str, mover_side: str, after_fen: str) -> bool:
    fields = after_fen.split(); fields[1] = mover_side; pseudo = " ".join(fields)
    for move in pyffish.legal_moves("chess", pseudo, []):
        if pyffish.gives_check("chess", pseudo, [move]):
            child = pyffish.get_fen("chess", pseudo, [move])
            if not pyffish.legal_moves("chess", child, []): return True
    return False


def enrich(profile: dict, include_mate: bool) -> dict:
    moves = profile["Moves"].split(); values = []
    for node in profile["nodes"]:
        ply = int(node["ply"]); fen = pyffish.get_fen("chess", profile["InitialFEN"], moves[:ply]); board = board_from_fen(fen); white = fen.split()[1] == "w"
        features = {move: move_features(fen, board, move, white) for move in pyffish.legal_moves("chess", fen, [])}
        solution_move = node["solution_uci"]
        solution = features[solution_move]
        after_fen = pyffish.get_fen("chess", fen, [solution_move])
        mate = mate_after_pass(fen, fen.split()[1], after_fen) if include_mate else False
        if mate and solution["level"] == 0:
            solution["level"] = 1
        candidate_floor = max(2, solution["level"])
        plausible_alternatives = 0
        directly_refuted = 0
        for candidate, item in features.items():
            if candidate == solution_move or item["level"] < candidate_floor:
                continue
            candidate_fen = pyffish.get_fen("chess", fen, [candidate])
            moved_piece = item["after_board"][candidate[2:4]]
            if immediately_refuted(candidate_fen, candidate, VALUES.get(moved_piece.upper(), 0), item["captured_value"]):
                directly_refuted += 1
            else:
                plausible_alternatives += 1
        metric = {
            "solution_forcing_level": solution["level"],
            "material_threat_value": solution["material_threat_value"],
            "mate_threat_after_pass": mate,
            "more_forcing_legal": sum(item["level"] > solution["level"] for item in features.values()),
            "same_forcing_legal": sum(item["level"] == solution["level"] for item in features.values()) - 1,
            "plausible_forcing_alternatives": plausible_alternatives,
            "directly_refuted_forcing_candidates": directly_refuted,
            "reply_branching_bits": round(math.log2(max(1, len(pyffish.legal_moves("chess", after_fen, [])))), 3),
        }
        node["forcingness"] = metric
        values.append(metric)
    mean = lambda key: round(sum(item[key] for item in values) / len(values), 3)
    metrics = profile["metrics"]
    metrics.update({"mean_solution_forcing": mean("solution_forcing_level"), "quiet_solution_fraction": round(sum(item["solution_forcing_level"] == 0 for item in values) / len(values), 3), "mean_material_threat_value": mean("material_threat_value"), "mate_threat_fraction": round(sum(item["mate_threat_after_pass"] for item in values) / len(values), 3), "mean_more_forcing_legal": mean("more_forcing_legal"), "mean_same_forcing_legal": mean("same_forcing_legal"), "mean_plausible_forcing_alternatives": mean("plausible_forcing_alternatives"), "mean_directly_refuted_forcing_candidates": mean("directly_refuted_forcing_candidates"), "mean_reply_branching_bits": mean("reply_branching_bits")})
    metrics["quietness_gap"] = round(metrics["mean_more_forcing_legal"] + 1.5 * metrics["quiet_solution_fraction"] + 0.35 * metrics["mean_reply_branching_bits"], 3)
    return profile


def main() -> None:
    config = args(); report = json.loads(config.input.read_text(encoding="utf-8"))
    report["profiles"] = [enrich(profile, config.mate_threats) for profile in report["profiles"]]
    report["forcingness_definition"] = {"levels": "0 quiet, 1 material or mate threat, 2 capture, 3 check, 4 check-and-capture", "material_threat": "new attack: target value if undefended, otherwise target minus cheapest attacker", "plausible_forcing_alternatives": "other check/capture-tier candidates excluding moves whose moved piece is immediately legally captured at a loss of at least two pawn units", "mate_threat_after_pass": "optional mate-in-one potential after a hypothetical opponent pass"}
    config.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {config.output} for {len(report['profiles'])} puzzle(s).")

if __name__ == "__main__": main()