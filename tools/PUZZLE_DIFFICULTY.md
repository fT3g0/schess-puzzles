# Puzzle Difficulty Estimation

This is a local research note for estimating human puzzle difficulty. It does not yet
produce a production rating. The primary validated target is **move-execution
difficulty**: how hard it is to find the moves of a supplied tactical line one decision
at a time. This is distinct from **position-evaluation difficulty**: how hard it is to
recognize from the starting position that a plan wins, draws, or loses.

## Benchmark

We use a deterministic, stratified subset of the local Lichess standard-chess puzzle
database. Lichess puzzle rating is used only as an imperfect human calibration for
move-execution difficulty. The current main benchmark has 500 puzzles across five
rating ranges, analyzed at engine depths 4, 6, 8, 10, and 12.

The useful validation number is leave-one-out Spearman correlation, not a training
correlation.

## Signals

| Signal | What it approximates | Current evidence | Main failure mode |
| --- | --- | --- | --- |
| Solver-line length | Number of player decisions | Individual Spearman 0.528 | A long forced sequence can be easy. |
| Low-depth decoys | Solution differs from shallow engine choice | 0.489 | Misses candidates that need a long verification but are already engine-clear. |
| Best-move switches | Candidate instability across depths | 0.560 | Engine instability is not always human difficulty. |
| Near-best moves | Ambiguity at shallow depth | 0.398 | Multiple engine-near moves can be obviously inferior to humans. |
| Candidate forcingness | Checks, captures, material/mate threats, reply width | Major addition to the baseline | A quiet but natural plan can be easier than a forcing-looking alternative. |
| Dominant candidate priority | Whether the solution is the top human-priority check/capture/threat candidate | Solution rank alone: Spearman 0.482 | Static priority cannot tell whether a sacrifice has a real follow-up. |
| Plausible forcing alternatives | Similar forcing candidates after removing immediate material blunders | Raised the combined model from 0.711 to 0.736 | Does not catch alternatives that fail only after a longer line. |
| Plan-preserving defenses | Defender replies grouped when the known next move still works | Raised the combined model to 0.740 | Uses the known Lichess line and still cannot verify a long win beyond it. |
| Static forcing-tree size | Pseudo-forcing replies after a move | Not retained; tree-only correlation 0.286 | Counts technical defenses and treats attacker/defender too symmetrically. |

The current best exploratory composite is **forcing + solution-aware defense
equivalence**, with leave-one-out Spearman **0.740** on the 500-puzzle sample.
This is promising but not a final rating model.

## What Human Feedback Established

- A puzzle is often easy when the solution is the clearly first candidate: usually a
  safe check-and-capture, check, or capture, followed by one obvious continuation.
- Raw defender branching is misleading. Several legal evasions should count as one
  practical branch when they all leave the same winning follow-up intact.
- Candidate safety matters: an apparently forcing move that simply lands on a defended
  square is often rejected by pattern recognition, not calculated as a serious line.
- Long forced-looking sequences can still be difficult if the material win or mating
  pattern is only visible far beyond the stored puzzle line.
- Pawn endgames and conversions are a separate blind spot. King routes, passed-pawn
  races, tempi, and opposition can be decisive even when no move is a check, capture,
  or ordinary threat.

## Next Experiments

1. **Human-visible variant-tree budget**: construct the tree *before* the solution,
   from plausible attacker candidates rather than all legal moves. Keep a branch only
   when it survives quick human-style rejection (obvious recapture, immediate material
   loss, or a clearly dominated capture) and only split defender replies when they
   change the available plan. Measure the total relevant plies across these branches,
   not just the maximum depth of one engine PV. This is the current priority.
2. **Human termination criteria**: stop a relevant branch when mate is forced, a
   material gain is secure and uncomplicated, or one continuation works against an
   entire reply class. These criteria are needed to make `cdC9G`, `uAywj`, `L6EPI`,
   and `fe78z` reliably simple rather than merely legally broad.
3. **Endgame progress model**: develop continuous signals for promotion distance,
   king-route distance, passed-pawn races, and material simplification. Do not switch
   abruptly to a separate "endgame" algorithm; instead let these signals matter more
   as the board empties. This addresses examples such as `beCgm`, where tempo counting
   forms the real variant tree.
4. **Verification horizon, later**: engine depth stability may help as a secondary
   descriptor of position-evaluation difficulty, but it is not currently the priority
   for move-execution difficulty. A high engine depth can reflect an engine's limited
   evaluation function rather than a large human-visible calculation tree.
5. **Keep the two targets separate**: validate move execution against Lichess, but
   validate position-evaluation difficulty later with curated human judgments or a
   dedicated practical-position task.

Candidate dominance was tested with sacrifice debt kept secondary to forcingness: a
speculative check/capture stays ahead of a quiet move, but is marked if immediately
recapturable. The full composite remained neutral (0.734 versus the 0.735 forcing
baseline), and material debt alone was weak. This supports using sacrifice debt as
context when building the visible tree, rather than as a standalone difficulty proxy.
## Local Tools

- `tools/lichess_move_difficulty_benchmark.py`: engine-depth and line data.
- `tools/forcingness_analysis.py`: static checks/captures/threats and candidate safety.
- `tools/solution_tree_analysis.py`: plan-preserving defender-equivalence classes.
- `tools/complexity_composite_analysis.py`: transparent feature sets and leave-one-out
  validation.
- `tools/*outlier*.py`: inspection reports, not production code.