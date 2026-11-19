"""Small offline GUI for converting Chess.com Seirawan PGN4 to PyChess PGN."""

from __future__ import annotations

import argparse
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schess_puzzles.schess_pgn import pgn4_to_pychess_pgn


class Pgn4ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Chess.com PGN4 to PyChess PGN")
        root.minsize(880, 680)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(3, weight=1)

        header = ttk.Label(
            root,
            text="Chess.com Seirawan PGN4 to PyChess PGN",
            font=("Segoe UI", 15, "bold"),
        )
        header.grid(row=0, column=0, sticky="w", padx=14, pady=(14, 4))

        input_frame = ttk.LabelFrame(root, text="Paste Chess.com PGN4")
        input_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=6)
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)
        self.input_text = tk.Text(input_frame, wrap="word", undo=True, height=18)
        self.input_text.grid(row=0, column=0, sticky="nsew", padx=7, pady=7)

        controls = ttk.Frame(root)
        controls.grid(row=2, column=0, sticky="ew", padx=14, pady=6)
        ttk.Button(controls, text="Convert", command=self.convert).pack(side="left")
        ttk.Button(controls, text="Open PGN4 file", command=self.open_file).pack(side="left", padx=(8, 0))
        self.copy_button = ttk.Button(controls, text="Copy PGN", command=self.copy_output, state="disabled")
        self.copy_button.pack(side="right")
        self.save_button = ttk.Button(controls, text="Save .pgn", command=self.save_output, state="disabled")
        self.save_button.pack(side="right", padx=(0, 8))

        output_frame = ttk.LabelFrame(root, text="PyChess-ready PGN")
        output_frame.grid(row=3, column=0, sticky="nsew", padx=14, pady=6)
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output_text = tk.Text(output_frame, wrap="word", undo=True, height=18, state="disabled")
        self.output_text.grid(row=0, column=0, sticky="nsew", padx=7, pady=7)

        self.status = tk.StringVar(value="Paste a PGN4 export, then select Convert. Nothing is uploaded.")
        ttk.Label(root, textvariable=self.status).grid(row=4, column=0, sticky="w", padx=14, pady=(2, 12))
        root.bind("<Control-Return>", lambda _event: self.convert())
        self.input_text.focus_set()

    def open_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Open Chess.com PGN4 export",
            filetypes=[("PGN4 text", "*.pgn4 *.txt"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            source = Path(selected).read_text(encoding="utf-8-sig")
        except OSError as error:
            messagebox.showerror("Could not open file", str(error), parent=self.root)
            return
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", source)
        self.status.set(f"Loaded {Path(selected).name}. Select Convert.")

    def convert(self) -> None:
        source = self.input_text.get("1.0", "end-1c").strip()
        if not source:
            messagebox.showinfo("No PGN4", "Paste a Chess.com PGN4 export first.", parent=self.root)
            return
        try:
            converted = pgn4_to_pychess_pgn(source)
        except (ValueError, RuntimeError) as error:
            self.copy_button.configure(state="disabled")
            self.save_button.configure(state="disabled")
            messagebox.showerror("Conversion failed", str(error), parent=self.root)
            self.status.set("Conversion failed. The input remains unchanged for correction.")
            return
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", converted)
        self.output_text.configure(state="disabled")
        self.copy_button.configure(state="normal")
        self.save_button.configure(state="normal")
        variation_count = source.count("(")
        detail = " including variation(s)" if variation_count else ""
        self.status.set(f"Converted successfully{detail}. Copy it or save it for PyChess Import Game.")

    def copy_output(self) -> None:
        output = self._output()
        if not output:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(output)
        self.root.update()
        self.status.set("PGN copied to the clipboard.")

    def save_output(self) -> None:
        output = self._output()
        if not output:
            return
        source = self.input_text.get("1.0", "end-1c")
        game_number = re.search(r'^\[GameNr\s+"(\d+)"\]', source, re.MULTILINE)
        default_name = f"chesscom_{game_number.group(1)}.pgn" if game_number else "seirawan_game.pgn"
        selected = filedialog.asksaveasfilename(
            title="Save PyChess PGN",
            defaultextension=".pgn",
            initialfile=default_name,
            filetypes=[("PGN", "*.pgn"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            Path(selected).write_text(output, encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Could not save PGN", str(error), parent=self.root)
            return
        self.status.set(f"Saved {Path(selected).name}. Use PyChess: Import Game.")

    def _output(self) -> str:
        return self.output_text.get("1.0", "end-1c")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Convert a PGN4 file without opening the GUI.")
    parser.add_argument("--output", type=Path, help="Output .pgn path for --input mode.")
    args = parser.parse_args()

    if args.input:
        output = pgn4_to_pychess_pgn(args.input.read_text(encoding="utf-8-sig"))
        target = args.output or args.input.with_suffix(".pgn")
        target.write_text(output, encoding="utf-8")
        print(f"Wrote {target}")
        return
    if args.output:
        parser.error("--output requires --input")

    root = tk.Tk()
    Pgn4ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
