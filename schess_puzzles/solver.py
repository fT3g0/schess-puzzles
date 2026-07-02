from __future__ import annotations

from pathlib import Path

from .store import read_jsonl


def solve_jsonl(path: Path) -> None:
    puzzles = read_jsonl(path)
    if not puzzles:
        print("No puzzles found.")
        return

    for index, puzzle in enumerate(puzzles, start=1):
        print(f"\nPuzzle {index}/{len(puzzles)}")
        print(f"Variant: {puzzle.variant}")
        print(f"FEN: {puzzle.fen}")

        for ply, expected in enumerate(puzzle.moves, start=1):
            guess = input(f"Move {ply}: ").strip()
            if guess == expected:
                print("Correct.")
                continue

            print(f"Incorrect. Expected: {expected}")
            break
        else:
            print("Solved.")

