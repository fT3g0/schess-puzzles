# Position Complexity Experiments

This local subproject profiles several signals separately instead of declaring a final
human difficulty rating too early.  Engine depth is a probe for tactical instability,
not a stand-in for human chess understanding.

## First signals

- **Structural load:** legal-move width, adjusted for checks and captures.
- **Instability load:** best-move changes and best-evaluation swing across depths.
- **Ambiguity:** number of moves within 100 cp of the final best move.
- Raw move counts, checks, captures, promotions and gates are retained so candidate
  formulas can be reweighted after human inspection.

## Run a small comparison

```powershell
python .\tools\position_complexity.py --fen-file .\data\complexity\seed_positions.txt --depths 4,6,8,10,12
```

The input is one FEN per line.  It may start with `label<TAB>` to keep the resulting
comparison readable.  Output is local JSON in `data/complexity/position_profiles.json`.

Useful next experiments are to compare tactical middlegames, quiet pawn endgames, and
human-curated puzzles; then record a small human complexity judgement beside each FEN.
## Lichess Rating Benchmark

A local Lichess `lichess_db_puzzle.csv.zst` can act as an external, human-calibrated
benchmark. The script samples the original data deterministically across five puzzle
rating ranges, applies the first opponent move (the actual solver position), and reports
Pearson and Spearman correlations between the provisional signals and Lichess rating. It also writes the strongest metric's highest positive and negative rating residuals for manual inspection.

```powershell
python .\tools\lichess_complexity_benchmark.py --per-bucket 5 --depths 4,6,8,10,12
```

The script uses the local database at `E:\Documents\Schach\Database\lichess_db_puzzle.csv.zst` by default and writes a small sample CSV plus a local JSON benchmark report under `data\complexity`.
## Two Difficulty Targets

The experiments now distinguish **move-by-move execution difficulty** from
**position-evaluation difficulty**. Lichess puzzle rating is used only for the former:
it is a task of selecting the correct continuation after the opponent's first move.
The latter remains an independent position-level profile for future validation.

```powershell
python .\tools\lichess_move_difficulty_benchmark.py --per-bucket 10 --depths 4,6,8,10,12
```

For every solver move in the known Lichess line, this probes whether the solution is
already selected at shallow depth, how many near-best moves exist, and whether a shallow
best move is replaced by the supplied solution at higher depth. These are provisional
signals for tempting alternatives and calculation difficulty.
### Composite Checks

The move-difficulty report can be combined without additional engine analysis. The helper
compares transparent equal-weight signals with ridge regression evaluated by leave-one-out
prediction; do not treat a training-only correlation as evidence.

```powershell
python .\tools\complexity_composite_analysis.py .\data\complexity\lichess_move_difficulty_25.json
```
### Forcingness And Candidate Order

`forcingness_analysis.py` distinguishes quiet moves, captures, checks, and
check-and-captures. It records how many legal moves are more forcing than each supplied
solution move, plus the opponent's reply branching after that move. This is a static
proxy for human candidate ordering; it is intentionally separate from engine instability.

```powershell
python .\tools\forcingness_analysis.py .\data\complexity\lichess_move_difficulty_200.json
python .\tools\complexity_composite_analysis.py .\data\complexity\lichess_move_difficulty_forcing_200.json
```
### Material And Mate Threats

`forcingness_analysis.py` now also treats a newly created material attack as a threat.
An undefended target contributes its full pawn-unit value; for a defended target, the
provisional value is `target - cheapest attacker`, never below zero. The S-Chess-capable
board geometry includes Hawk and Elephant attack patterns.

The optional `--mate-threats` mode records a deliberately conservative "mate in one if
the opponent passes" potential only on the supplied solution move. On the first 200
Lichess benchmark it did not improve cross-validated prediction, so it remains a
separate experimental signal rather than a default model feature.
### Larger Samples And Outlier Diagnostics

Use a larger deterministic, stratified sample before drawing conclusions from the
correlations. The outlier CSV contains every component's raw value, percentile within
the sample, fitted-model contribution, and one compact entry for every player decision
in the supplied line. This makes it practical to inspect whether a residual comes from
a low-depth decoy, instability, a quiet solution among forcing alternatives, or a
missing signal.

```powershell
python .\tools\lichess_move_difficulty_benchmark.py --per-bucket 100 --depths 4,6,8,10,12 --output .\data\complexity\lichess_move_difficulty_500.json --review-output .\data\complexity\lichess_move_difficulty_review_500.csv
python .\tools\forcingness_analysis.py .\data\complexity\lichess_move_difficulty_500.json --output .\data\complexity\lichess_move_difficulty_threat_500.json
python .\tools\complexity_composite_analysis.py .\data\complexity\lichess_move_difficulty_threat_500.json --output .\data\complexity\lichess_move_composites_threat_500.json --prediction-output .\data\complexity\lichess_move_composite_predictions_threat_500.csv
python .\tools\complexity_outlier_report.py .\data\complexity\lichess_move_difficulty_threat_500.json --output .\data\complexity\lichess_move_outliers_500.csv
```
### Plausible Forcing Alternatives

The candidate-order experiment also distinguishes a merely forcing move from one a
player must seriously calculate. For each solution node it counts other checks and
captures at least as forcing as the solution, but removes candidates whose moved piece
can immediately be legally captured for a material loss of at least two pawn units.
This handles obvious queen sacrifices such as a check that just loses the queen, while
preserving alternatives which need actual calculation. It is deliberately a first
static approximation: variants that fail only after a longer forcing sequence remain a
known next target.
### Bounded Forcing-Tree Probe

`forcing_tree_analysis.py` expands a static tree after each supplied solution move.
While in check it follows every legal reply; otherwise it follows checks and captures.
The first practical implementation is intentionally capped at 32 nodes and two further
plies, because a naive four-ply expansion is too slow for the full 500-puzzle sample.

On the 200-puzzle validation set the tree-aware ridge model reached Spearman `0.685`,
slightly below the forcing-aware baseline (`0.688`). This means raw static tree size is
not currently a useful default feature. It remains a useful diagnostic, but the next
iteration should model a *verification horizon* or engine-backed candidate refutation,
not simply expand more pseudo-forcing nodes.

```powershell
python .\tools\forcing_tree_analysis.py .\data\complexity\lichess_move_difficulty_threat_width_200.json --plies 2 --output .\data\complexity\lichess_move_difficulty_tree_200.json
```
### Solution-Aware Defense Equivalence

`solution_tree_analysis.py` corrects the main defect of the symmetric static tree:
its root is the attacker decision before the supplied solution, while the defender's
replies are compressed by their effect on the known next solver move. Every reply that
leaves that move legal belongs to one plan-preserving class; replies that prevent it
remain separate. This captures cases where many check evasions exist but `Qxc4`, for
example, works against all of them.

On the 500-puzzle benchmark the solution-aware signals alone are not enough (`0.713`
LOOCV Spearman), but adding them to the forcing-aware model improves it from `0.735`
to `0.740`. It is therefore retained as a small, interpretable supplementary signal.
Pawn-endgame tempo decisions remain largely invisible to this model and require a
separate, more general horizon/goal representation.

```powershell
python .\tools\solution_tree_analysis.py .\data\complexity\lichess_move_difficulty_threat_width_500.json --output .\data\complexity\lichess_move_difficulty_solution_tree_500.json
```