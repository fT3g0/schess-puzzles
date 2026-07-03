# S-Chess Puzzle Generator

Local-first tooling for generating and solving Seirawan chess / S-Chess tactics.

The project is designed as an orchestration layer around
[`chess-variant-puzzler`](https://github.com/ianfab/chess-variant-puzzler), Fairy-Stockfish,
and game sources such as pychess.org and chess.com.

## Pipeline

1. Fetch games from configured sources.
2. Normalize source files into PGN or pychess JSON.
3. Convert games to candidate positions in EPD/FEN.
4. Run `chess-variant-puzzler` to detect tactical positions.
5. Filter, validate, and export puzzles as EPD/PGN/JSON.
6. Apply the local S-Chess selector for stricter only-move tactics.
7. Solve puzzles locally in a terminal UI.

`chess-variant-puzzler` already covers the middle of the pipeline:

- generating positions from engine games,
- converting pychess JSON to EPD,
- converting PGN to EPD,
- identifying puzzles using Fairy-Stockfish,
- filtering puzzle candidates,
- exporting annotated EPD to PGN.

This repository focuses on the S-Chess-specific orchestration, source acquisition,
configuration, metadata, and local solving experience.

## Source Formats

### pychess

pychess PGN keeps Seirawan insertion notation such as `Ng6/H`, `Rb7/E`, and
`O-O/Eh1`. These files can be parsed directly.

### chess.com

The standard chess.com Seirawan PGN export is currently treated as unsuitable for
this project. In the observed sample, insertion information is missing and the
movetext can contain empty move slots, so the game cannot be reconstructed
legally.

Use chess.com's PGN4 export instead. PGN4 stores the full 4-player-board
coordinate system plus explicit insertion markers such as:

```text
Ne11-f9&@yH-e11
O-O&@rE-h4
```

The local parser maps the embedded 8x8 board from PGN4 coordinates to normal
UCI:

```text
d4..k4  -> a1..h1
d11..k11 -> a8..h8
```

Insertion markers are converted to Fairy-Stockfish's `h` / `e` UCI suffixes.
For example:

```text
Ne11-f9&@yH-e11 -> b8c6h
O-O&@rE-h4      -> e1g1e
```

Current scraper status:

- pychess public game pages can be downloaded directly because the page embeds
  the full PGN in `data-board`.
- chess.com public monthly PGN API exists for normal games, but the standard PGN
  is lossy for Seirawan insertion moves.
- chess.com PGN4 is parseable once saved locally, but public guest pages do not
  expose PGN4 in the HTML.
- The chess.com variants app uses `wss://variants.gcp-prod.chess.com`.
  Game loading sends a WebSocket message:

```json
{"action":"game","data":{"gameNr":103834722,"action":"join"}}
```

  Archive search sends `search-archive` with parameters such as `playerId`,
  `days`, `gameType`, `ratingType`, and `title`.
- Guest access can open the WebSocket, but does not receive game/archive data.
  Use an authenticated chess.com cookie through `CHESSCOM_COOKIE` or `--cookie`.

Useful source commands:

```powershell
python -m schess_puzzles.cli fetch-pychess 1eCeqqvX
python -m schess_puzzles.cli discover-pychess https://www.pychess.org/1eCeqqvX
python -m schess_puzzles.cli fetch-chesscom fT3g0 2026 06
python -m schess_puzzles.cli fetch-chesscom-pgn4 103834722
python -m schess_puzzles.cli discover-chesscom-archive --username fT3g0 --pages 1
```

For authenticated chess.com variants scraping:

```powershell
$env:CHESSCOM_COOKIE = "your_chesscom_cookie_string"
python -m schess_puzzles.cli discover-chesscom-archive --username fT3g0 --days 0-9999 --pages 1
python -m schess_puzzles.cli fetch-chesscom-pgn4 103834722
python -m schess_puzzles.cli fetch-chesscom-archive --days 0-9999 --title seirawan --pages 3
```

Without `CHESSCOM_COOKIE`, chess.com PGN4 commands fail cleanly.

If you have copied only the Chess.com `ACCESS_TOKEN`, save it locally as
`access_token.txt` and use the integrated scrape/analyze command:

```powershell
python -m schess_puzzles.cli chesscom-next-tactics 20 --pages 50 --auth-user-id 7448926
```

`ACCESS_TOKEN` alone authenticates the websocket but does not expose the numeric
variants user id in the HTML page context. Pass it with `--auth-user-id`, set
`CHESSCOM_USER_ID`, or add a second line to `access_token.txt` such as
`CHESSCOM_USER_ID=7448926`.

The command reads `access_token.txt` by default, downloads the next new Seirawan
PGN4 files it can find in the archive search, analyzes exactly those files as the
next `chesscom_batchNN`, refreshes review reports, updates `web/public/puzzles.json`,
and syncs `docs/` for GitHub Pages. The token file is ignored by git.
`fetch-chesscom-archive` discovers archive game numbers and downloads each PGN4
file into `data/raw`. It skips existing files and waits one second between
downloads by default:

```powershell
python -m schess_puzzles.cli fetch-chesscom-archive --days 0-9999 --title seirawan --pages 3 --delay 1
```

To expand beyond one known player, use the bounded frontier crawler. It starts
from one or more player IDs or usernames, searches their variants archive,
downloads unseen PGN4 games, reads both players from the PGN4 headers, and queues
new usernames for later archive searches:

```powershell
python -m schess_puzzles.cli crawl-chesscom --player-id 7448926 --days 0-9999 --pages 1 --max-players 20 --max-games 500 --delay 1
```

The crawler deduplicates games during the run and skips files that already exist
in `data/raw`. The frontier is currently in memory only; the next scaling step is
a persistent crawl-state file so long crawls can resume cleanly.

For Seirawan, prefer all-time archive searches (`--days 0-9999`) because the
monthly active player pool is small. Keep `--title seirawan` as the first
attempt so the archive search itself does the variant filtering. Use
`--title "" --debug-socket` only as a diagnostic fallback to inspect what fields
Chess.com sends for broader variant results.

The most efficient Chess.com path is global title search without a player seed:

```powershell
python -m schess_puzzles.cli discover-chesscom-archive --days 0-9999 --title seirawan --pages 5 --debug-socket
python -m schess_puzzles.cli fetch-chesscom-archive --days 0-9999 --title seirawan --pages 5 --delay 1
```

Use `--start-page` to continue a previous archive sweep without rediscovering
and skipping earlier pages:

```powershell
python -m schess_puzzles.cli fetch-chesscom-archive --days 0-9999 --title seirawan --start-page 50 --pages 5 --delay 1
```

Use seeded crawling from known Seirawan players only when you want to expand a
specific player neighborhood or when global title search stops returning new
games.

## Finding More Games

Current discovery modes:

- pychess: extract public game IDs from pages and then fetch game PGNs.
- chess.com: authenticated variants archive search by `playerId` or resolvable
  username.
- local self-play: generate low-strength Fairy-Stockfish vs Fairy-Stockfish
  Seirawan PGNs for tactical mistake mining.

To discover games where the local user did not play, use the same chess.com
archive endpoint with broader filters:

- Search by another known `playerId`.
- Search by a known opponent username/player id.
- Search all time with `title=seirawan` first; this is much more useful for a
  low-volume variant than recent-only discovery.
- Use archive result expansion: each downloaded game reveals both players, so
  their player IDs can be queued for later archive searches.

The implemented first pass is the `crawl-chesscom` frontier crawler:

1. Start with one or more seed player IDs.
2. Download their Seirawan archive pages.
3. Fetch PGN4 for each game.
4. Parse both players from PGN4 headers.
5. Add unseen player IDs to a queue, with per-player/page limits.
6. Deduplicate by chess.com `GameNr`.

At the moment, queued opponents are stored as usernames and resolved through the
authenticated variants socket when their turn is reached.

## Engine Self-Play

Low-strength engine self-play is useful for manufacturing tactical mistakes.
The generator uses Fairy-Stockfish at shallow depth and randomly chooses among
MultiPV candidates, with an optional pure-random blunder chance:

```powershell
python -m schess_puzzles.cli selfplay --games 20 --output-dir data\raw\selfplay --prefix fs_d1 --depth 1 --multipv 6 --max-plies 120 --temperature-cp 250 --blunder-chance 0.20 --seed 1
```

You can also use Fairy-Stockfish's UCI strength controls. This is useful for
comparing whether very weak play creates too many obvious/non-forcing blunders:

```powershell
python -m schess_puzzles.cli selfplay --games 20 --output-dir data\raw\selfplay_skill2 --prefix fs_s2 --depth 1 --skill-level 2 --multipv 6 --max-plies 120 --temperature-cp 250 --blunder-chance 0.15 --seed 2
python -m schess_puzzles.cli selfplay --games 20 --output-dir data\raw\selfplay_skill3 --prefix fs_s3 --depth 1 --skill-level 3 --multipv 6 --max-plies 120 --temperature-cp 250 --blunder-chance 0.15 --seed 3
```

If a GUI's "level" maps to Elo-limited UCI play instead of `Skill Level`, use:

```powershell
python -m schess_puzzles.cli selfplay --games 20 --output-dir data\raw\selfplay_elo --prefix fs_e1200 --depth 1 --uci-limit-strength --uci-elo 1200 --multipv 6 --max-plies 120 --temperature-cp 250 --blunder-chance 0.10 --seed 4
```

The output is normal Seirawan PGN and can be fed into the same selector:

```powershell
python -m schess_puzzles.cli select-batch --glob "data/raw/selfplay/*.pgn" --limit 20 --depth 10 --multipv 6 --extend-critical --max-plies 5 --output-jsonl data\puzzles\selfplay_batch01.jsonl --report-jsonl data\puzzles\selfplay_batch01_report.jsonl
python -m schess_puzzles.cli review-html data\puzzles\selfplay_batch01_report.jsonl data\puzzles\selfplay_batch01_review.html
```

For repeated batch generation, use the PowerShell helper instead of typing every
selector/review command manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\Generate-Batches.ps1 -ChessComStartBatch 50 -ChessComBatches 5 -Combine
powershell -ExecutionPolicy Bypass -File .\tools\Generate-Batches.ps1 -SelfPlayStartBatch 8 -SelfPlayBatches 3
powershell -ExecutionPolicy Bypass -File .\tools\Generate-Batches.ps1 -ChessComStartBatch 50 -ChessComBatches 5 -SelfPlayStartBatch 8 -SelfPlayBatches 2 -Combine
```

Chess.com batch numbers map to raw-game offsets by `start_index = (batch - 1) *
20`. Self-play keeps the level-1 style settings from the first useful run:
depth 1, MultiPV 6, temperature 250cp, and 20% random blunders. It also lets
the weaker side resign after a sustained losing eval by default:
`-ResignCp 700 -ResignMoves 5`.

The selector skips positions that have no hawk/elephant on the board or in
reserve, because those are standard-chess tactics and are less useful for this
project. Use `--include-standard-positions` on `select` or `select-batch` if you
need to reproduce the older broader scan.

For an unattended Chess.com run, use the scraper+batch helper. It fetches archive
pages in chunks, skips already downloaded PGN4 files, processes every newly
available batch, and writes a transcript under `logs/`:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\Run-ChessCom-Unattended.ps1 -ArchiveStartPage 50 -ArchivePages 50 -ArchiveChunkPages 5 -DownloadDelay 1
```

Stop it with `Ctrl+C` when needed. Already downloaded PGN4 files, completed
batch reports, eval-cache entries, and generated review pages remain on disk.
Rerun the same command to resume; existing downloads and completed batches are
skipped by file presence.

## Tactic Selection

The upstream puzzler is useful, but its criteria are broader than the intended
S-Chess puzzle definition here. It uses a sigmoid best-vs-second-best gap and can
classify positions as defensive even when the side to move remains lost.

The local selector in `schess_puzzles.selector` uses explicit outcome bands:

- `winning`: best move is in winning territory and the second-best move is not.
- `drawing`: best move reaches at least drawing territory and the second-best
  move is in the losing range.
- `min-gap-cp`: best and second-best must also be separated by a clear centipawn
  gap.

Default thresholds:

```text
win_cp = 200
draw_floor_cp = -80
losing_cp = -150
min_gap_cp = 150
```

These are intentionally configurable because shallow engine scores around the
draw boundary are noisy. For example, a move scored `-100` with all alternatives
below `-280` is a plausible drawing tactic, but it misses the default
`draw_floor_cp = -80`.

For batch generation, keep the first pass shallow enough to be efficient and
confirm only the candidate tactics at higher depth:

```powershell
python -m schess_puzzles.cli select-batch --depth 10 --multipv 6 --confirm-depth 20 --confirm-multipv 6 --extend-critical --max-plies 5
```

The PowerShell batch helper uses this two-stage setup by default. If a candidate
does not remain the same tactic with the same best move at the confirmation
depth, it is dropped.

One-move recaptures are detected as `recapture` flags. They can be kept for pure
evaluation debugging or removed for puzzle quality:

```powershell
python -m schess_puzzles.cli select pychess-variants_1eCeqqvX --exclude-recaptures
```

## Critical Continuations

Puzzle lines should not be limited to the moves played in the source game. After
the first selected move, the selector can search legal opponent replies that
force another only move for the solver side:

```powershell
python -m schess_puzzles.cli select pychess-variants_0bQHMZ37 --extend-critical
```

This mirrors the common standard-chess puzzle approach: an opponent reply may be
chosen because it creates the next only move, even if that reply was not played
in the game. The selector prefers quiet forcing replies over checking replies by
default, because otherwise many lines are extended by obvious bad checks.

Use `--allow-check-reply-first` to disable that preference.

## Static Puzzle Website

The public-facing puzzle viewer is designed as a static site. Python remains the
offline factory for scraping, engine analysis, filtering, and report generation;
the browser only consumes an exported JSON file and checks the known tactic line.
This keeps hosting simple and leaves room for a later backend without coupling
puzzle generation to the web UI.

Generate the current web payload from the combined report:

```powershell
python -m schess_puzzles.cli export-web data\puzzles\all_report.jsonl web\public\puzzles.json
```

Run the local static site:

```powershell
python -m http.server 8765 -d web
```

Then open `http://localhost:8765`. Hidden-by-default tactics are still exported
with tags such as `standard-like`, `trivial-recapture`, `trivial-capture`, and
`check-evasion`, so the frontend can expose or suppress them without another
engine pass.

For GitHub Pages, sync the generated `web/` folder into `docs/` before
committing:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\Publish-WebToDocs.ps1
```

To grow the public set from local Fairy-Stockfish self-play until a target
visible count is reached:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\Grow-SelfPlayToTarget.ps1 -TargetVisible 500
```

The growth script is resume-aware. If it is interrupted after generating raw
self-play PGNs but before analysis finishes, rerunning it reuses the existing raw
batch. It also recombines reports, exports `web/public/puzzles.json`, and syncs
`docs/` after each completed batch.

Current rough yield baseline: Chess.com real games produced about 121 visible
puzzles from 1342 games, while local self-play batches produced about 47 visible
puzzles from 260 generated games. Self-play is denser per game, but the confirmed
engine analysis is the bottleneck, so reaching 500 visible puzzles is an
unattended multi-hour run at the current settings.## Setup

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Clone or place `chess-variant-puzzler` somewhere locally, then update
`config.example.toml` and save it as `config.toml`.

The default Fairy-Stockfish path is:

```text
E:\Documents\Schach\Engines\Fairy_Stockfish\fairy-stockfish_x86-64-modern.exe
```

## Quick Start

```powershell
python -m schess_puzzles.cli init-config
python -m schess_puzzles.cli pipeline --config config.toml --input pychess-variants_1eCeqqvX
python -m schess_puzzles.cli solve data/puzzles/puzzles.jsonl
```

The scaffold is intentionally conservative: source fetchers can be expanded per
site once the exact endpoints and account requirements are known.


