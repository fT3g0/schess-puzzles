# Puzzle Difficulty Research

## Purpose and scope

This is a local research subproject. It estimates **move-execution difficulty**:
how difficult it is for a player to find the next moves of a tactic puzzle. It is
not yet used to label or filter the public S-Chess puzzle set.

Lichess standard-chess puzzle ratings are the external target. They are useful for
move-execution difficulty because Lichess presents a puzzle one move at a time.
They are not a direct target for **position-evaluation difficulty**, which asks how
hard it is to recognize that the initial position is favorable at all.

Unless noted otherwise, reported correlations are Spearman correlations against
Lichess rating. Higher is better. The 500-profile benchmark is deterministic and
stratified over rating ranges; its predictions are evaluated out of sample. The
30-profile prototypes are diagnostic only and must not be compared directly with
the 500-profile results.

## Current best validated result

The best transparent model so far is a standardized Ridge regression named
`forcing_solution_aware`:

- Dataset: 500 Lichess profiles from 304 games.
- Evaluation: leave-one-out prediction.
- Pearson: `0.739`; Spearman: `0.740`.
- Feature groups: known line length, low-depth engine instability, candidate
  forcingness, plausible forcing alternatives, reply branching, and
  solution-aware defense compression.

The closely related `visible_tree_aware` Ridge reaches Spearman `0.739`. This
means the current best result is encouraging, but not a finished human model:
some features overlap, several coefficients are unstable under correlation, and
important tactical/endgame cases are still mischaracterized.

### Largest Ridge coefficients in the best model

Coefficients are standardized and therefore comparable within this one model;
they are not causal importance scores. Correlated features can share or reverse
weight, so the signs of the defense-compression pair must be interpreted with
care.

| Feature | Coefficient | Interpretation |
| --- | ---: | --- |
| `solver_nodes` | +189 | Longer supplied solution line tends to be harder. |
| `mean_solution_tree_bits` | +180 | More distinct relevant continuations along the supplied line. |
| `mean_best_move_switches` | +125 | Best move changes while shallow engine depth increases. |
| `mean_solution_forcing` | -69 | A more forcing solution is generally easier. |
| `mean_defense_equivalence_classes` / `mean_plan_breaking_replies` | -69 | Currently duplicated/correlated implementation; sign is not trustworthy alone. |
| `mean_reply_branching_bits` | +53 | More meaningful reply branching tends to be harder. |
| `mean_instability_load` | +51 | Larger shallow-depth evaluation instability. |
| `mean_more_forcing_legal` | +51 | More moves that are more forcing than the solution. |
| `mean_plausible_forcing_alternatives` | +41 | More serious forcing alternatives to inspect. |

## Approaches tested

| Approach | Sample and validation | Spearman | Result |
| --- | --- | ---: | --- |
| Low-depth ambiguity only | 200, LOOCV | 0.205 | Too weak by itself. |
| Engine instability only | 200, LOOCV | 0.546 | First consistently useful signal. |
| Core execution features | 200, LOOCV | 0.598 | Adds solution length and low-depth ambiguity. |
| Forcing-aware Ridge | 200, LOOCV | 0.688 | Strong jump from candidate ordering and reply branching. |
| Raw bounded forcing tree | 200, LOOCV | 0.286 | Bad: expands pseudo-forcing moves symmetrically. |
| Tree-aware Ridge | 200, LOOCV | 0.685 | Did not improve the forcing baseline. |
| Solution-aware defense Ridge | 500, LOOCV | 0.713 | Useful but insufficient on its own. |
| Forcing-aware Ridge | 500, LOOCV | 0.735 | Strong baseline. |
| Visible-tree-aware Ridge | 500, LOOCV | 0.739 | Best explicit calculation-budget variant. |
| Forcing-solution-aware Ridge | 500, LOOCV | **0.740** | Current best validated model. |
| Broad gradient-boosted trees | 500, grouped 5-fold | 0.723 | Competitive but below Ridge; feature interactions alone did not solve tree relevance. |
| Candidate-transition gradient boosting | 500, grouped 5-fold | 0.711 | Extra transition/material features did not improve prediction. |
| Selective human-search prototype | 30, diagnostic | 0.438 to 0.511 | Explicit search works mechanically, but its visited nodes initially included too much unconscious candidate ranking. |
| Attention-tree prototype | 30, hand-calibrated diagnostic | 0.738 | Promising conceptual direction, but tuned on the same 30 examples and not validated. |
| Proof/disproof prototype | 30, diagnostic | 0.621 | Better certificates than naive search, but goal proofs are still too weak. |

## Signals retained for future work

- **Forcingness and candidate order:** check-capture, check, capture, material
  threat, then quiet move. A correct highest-forcing candidate is often easy.
- **Plausible alternatives:** not every legal move matters. A forcing move that
  loses a major piece immediately is normally a quick rejection, while a safe
  forcing alternative deserves calculation.
- **Low-depth instability:** changing best moves and evaluation swings at depths
  4, 6, 8, 10, and 12 correlate strongly with difficulty.
- **Material context and conversion:** material deficit, material debt from a
  sacrifice, immediate recovery, simplification, and a clear material edge can
  determine when a human stops calculating.
- **Tempo threat:** compare a position with the side to move against a pseudo
  turn-flipped position at low depth. A large evaluation drop may reveal that
  the opponent currently has a threat.
- **Solution-aware defense classes:** defender replies should be grouped when
  they leave the same known continuation available. Raw legal reply counts are
  usually misleading.
- **Visible calculation budget:** count plausible candidate branches and
  plan-breaking defenses, rather than ordinary engine plies.

## Why the general problem remains hard

The key object is a **relevant human calculation tree**, not the legal move tree
and not an engine principal variation. Its shape changes from position to
position. A human typically ranks most moves subconsciously, calculates only a
few candidates consciously, treats forced replies as free transitions, and
stops after a sufficiently certain conversion.

This produces two requirements that the feature models only approximate:

1. Candidate selection must allow a natural forcing move to be tried first, but
   must expand to other candidates when that idea is uncertain or fails.
2. A branch should terminate only after a goal-specific confidence certificate,
   such as a stable material win, a mating attack, a promotion, or a successful
   defense. A generic static evaluation can falsely accept an attractive but
   losing sacrifice.

## Important failure cases

These IDs are deliberately retained as regression examples, not dismissed as
noise. Detailed positions and traces are in the referenced local reports.

| Puzzle | What goes wrong | Lesson |
| --- | --- | --- |
| `izvDQ` | `Qf7+` is an obvious first candidate, but after the forced reply several forcing queen moves remain unresolved. Naive search undercounts the hard second decision; an unsafe queen capture must not be accepted automatically. | Separate a cheap initial candidate choice from the later unresolved decision; use compensation-aware rejection. |
| `dq5Md` | The natural captures/checks are wrong; the correct king move is initially counterintuitive. | A correct move outside the first forcing tier must trigger a tier descent and count as extra conscious work. |
| `jz5WN` | `Nf3+`, then immediate material wins, is easy for people but the early search counted many alternatives. | Latent candidate ranking and forced continuations should not count as conscious nodes. |
| `9D0y1` | Check-capture followed by a high-value capture is a very direct line, but a broad candidate search overestimates it. | Correct top-ranked forcing move plus immediate conversion should be close to one attention node. |
| `J9JZB` | Several checks exist, but `Qd7+` simplifies through a queen trade and reduces future branching. | Candidate quality includes game-state reduction, not only check/capture labels. |
| `AbYOY` | A natural forcing decoy must be calculated and refuted before the solution is sought. | Forcing alternatives of equal apparent strength are real calculation cost. |
| `c6NAD` | The right continuation remains ambiguous at shallow depth and branches before material is collected. | Conversion horizon and post-solution branch structure matter. |
| `JRGP0`, `WcJsr`, `LCuat`, `T5rPw`, `TuMM1` | Pawn-endgame tempos and long horizons are often engine-simple but human-hard. | Empty boards require a separate plan/horizon representation; forcingness alone is inadequate. |
| `UXxaf` | Once a rook is safely won, many theoretical opponent replies are irrelevant. | Strong conversion certificates must prune plan-breaking replies after a decisive gain. |
| `d6BJb` | A king attack stays intuitively dangerous even when some material is not captured. | Threat/attack goals cannot be reduced to immediate material accounting. |

## Current prototype directions

### Attention tree

The attention-tree model changes the unit of effort. One node is a consciously
examined candidate or a non-forced, plan-changing defense. Forced transitions
and unexamined candidate ordering are free. It activates the highest forcing
tier first, descends only when that tier lacks a success certificate, and
records the number of candidate nodes, critical defense nodes, and tier descents.

This model better matches the `jz5WN` and `9D0y1` intuition. Its 30-position
numbers are **not validation** because the rules were changed after inspecting
those examples. The next meaningful test is a frozen rule set on a fresh,
larger stratified sample.

### Proof/disproof search

This prototype labels candidates `PROVEN`, `DISPROVEN`, `OPEN`, or `DEFERRED`.
An attractive local continuation is not a proof: it needs a terminal,
material-conversion, mating-attack, promotion, or defensive certificate. It
addresses the central failure mode where a greedy forcing candidate looks good
at depth two but actually loses later.

The present certificates are only reliable for simple material conversions.
Goal-specific certificates for attacks, passed pawns, and defensive resources
are the main missing work.

## Files and reproducibility

- Overview and commands: `tools/POSITION_COMPLEXITY.md`.
- Feature model outputs: `data/complexity/lichess_move_composites_*.json`.
- Gradient-boosting outputs: `data/complexity/lichess_gradient_boost_*.json`.
- Feature-model outliers: `data/complexity/lichess_move_outliers_500.csv` and
  `data/complexity/visible_tree_budget_outliers_500.md`.
- Human-search traces: `tools/HUMAN_SEARCH_ENGINE.md` and
  `data/complexity/human_search_outliers_30.md`.
- Attention and proof-search traces: `data/complexity/attention_tree_outliers_30.md`
  and `data/complexity/proof_search_outliers_30.md`.

## Recommended next step

Freeze one attention-tree/proof rule set before changing it again, run it on a
fresh 200- or 500-puzzle stratified sample, and review its largest residuals.
The first certificates worth adding are: stable material conversion, forced
mate/king attack, promotion race, and defensive hold. Keep the existing Ridge
model as the validated baseline until such a search model beats it on an unseen
sample.

## Maia human-move calibration

Maia-2 is used only as a standard-chess research instrument. It predicts the
move distribution of human players at a chosen Elo, so it cannot be queried on
S-Chess positions, Hawk/Elephant pieces, or gating moves. The research goal is
to identify abstract, transferable signals rather than place Maia in production.

A first 500-puzzle benchmark used the existing deterministic Lichess sample and
kept puzzles from the same Lichess game together in each of five validation
folds. The Rapid Maia-2 checkpoint was queried at equal player/opponent Elos
800, 1200, 1600, 2000, and 2400. The useful compact feature set at 1200 was:
minimum and mean log probability of the supplied solution, solution rank,
gap from Maia's top move, top-1 match rate, and move-distribution entropy.

| Model | Grouped CV Spearman |
| --- | ---: |
| Maia compact signals only | 0.679 |
| Existing forcing + solution-aware baseline | 0.742 |
| Baseline + Maia compact signals | 0.826 |

The combined result remains 0.822-0.826 for Ridge regularization values 1, 5,
20, 50, and 100. The tested 800-to-1600 probability-gain features did not add
value. This is strong evidence that Maia captures human candidate preference
not represented by the present engine/forcing features, but it is still one
sample and one source. Before treating it as a final benchmark, repeat on a
fresh stratified sample or a later Lichess data slice.

The next S-Chess task is not to imitate Maia's neural network directly. Instead,
inspect the largest Maia-vs-baseline residuals and distill reusable concepts:
solution probability of the first natural candidate, rank and probability gap of
the intended move, and concentration of plausible human choices. Those concepts
can later be approximated from S-Chess candidate ordering, material context,
forcingness, and conversion certificates.

## Outcome clarity

`clarity` is a second local axis, intentionally independent of difficulty. It
answers: once the line has been found, how visibly does it establish its result?
It is intended for users who prefer tactical tasks with a concrete conclusion
rather than a line that only crosses an engine evaluation threshold.

The initial implementation is engine-free and relies on generation metadata
already stored in every record:

| Outcome | Initial score | Meaning |
| --- | ---: | --- |
| Checkmate | 100 | A terminal, directly verifiable conclusion. |
| Decisive material win (5+ pawn units) | 91-95 | Clear conversion, usually a queen/Hawk/Elephant or equivalent gain. |
| Major material win (3-4) | 85-89 | Clear piece-winning conclusion. |
| Minor material win (1-2) | 70-74 | Concrete but smaller conversion. |
| Forced repetition, when explicitly tagged | 66-70 | Clear drawn result, but less tangible than material or mate. |
| Positional winning advantage without material conversion | 36 | Engine evaluation remains important. |
| Defensive equality without repetition/material conversion | 29 | The archetypal low-clarity case. |

A small bonus recognizes a visibly forcing stored line. It cannot turn a
positional save into a high-clarity puzzle. The initial raw-report audit covered
10,075 records: 7,647 high, 890 medium, and 1,538 low. In the currently visible
3,744-puzzle export, the split is 1,961 high, 591 medium, and 1,192 low.
Examples such as `znevk` correctly land in low clarity because their material is
unchanged and the result is equality; a line that wins a Hawk or Elephant lands
high regardless of how difficult the tactical discovery was.

Clarity is now written by report enrichment and included in future `export-web`
payloads, but it has no website control yet. A future filter should wait for a
manual review of representative low/medium/high examples. The current cheap
version only recognizes repetition when it was already recorded in the report;
reconstructing every S-Chess line at export time was measured as too slow.
## Maia residual audit

`tools/maia_outlier_report.py` now compares the grouped cross-validated
forcing/solution-aware Ridge baseline with the combined baseline-plus-Maia
model, then writes the largest helpful and harmful cases to
`data/complexity/maia_baseline_outliers_500.md`.

The first audit supports a useful division of labour. Maia improves several
endgames which the hand-crafted model overestimates (`TuMM1`, `J9JZB`) because
human players tend to identify the only practical plan immediately. It also
raises difficult quiet or non-obvious solutions (`xhAid`, `c6NAD`, `AbYOY`) that
forcingness alone treats as too simple. Conversely, Maia can overestimate
simple mate patterns when its intended move is uncommon in ordinary games
(`xQJTx`, `nXNG0`, `MGyKH`). A future transferable model should therefore keep
explicit checkmate and clear-conversion certificates as strong corrective
features, while using Maia-style candidate preference for the less terminal
positions.

The report exposes the raw Maia probability, rank, top-1 fraction, gap, and
entropy beside the existing forcing/search signals, so human review can decide
which residuals reveal a missing general signal rather than benchmark noise.
## Transferable candidate-preference proxy

A new engine-free, variant-aware proxy is implemented in
`schess_puzzles/human_candidates.py`. It ranks legal candidates from the FEN
that each move actually produces, rather than assuming standard UCI semantics.
It therefore supports Seirawan gating, en passant and Chess960 castling. Its
ordering is deliberately coarse (check-capture, check, capture, visible
material threat, quiet), with only within-tier adjustments for material,
visible threat, simplification, opponent mobility and immediate hanging risk.
The resulting soft distribution supplies Maia-like proxy features: solution
probability/rank, top-priority fraction, gap from the top candidate, and
candidate entropy.

On the 500-puzzle grouped Lichess benchmark, the best individual proxy signal
(`proxy_min_log_probability`) reaches Spearman **-0.573**. The proxy alone has
Spearman **0.562** in grouped Ridge; added to the established forcing/solution
baseline it raises **0.742** to **0.750**. Added after Maia it makes no material
difference (**0.826** to **0.827**), which is expected: it recovers some of the
same human candidate-ordering information, but cannot replace Maia on
standard chess. This is nevertheless the relevant result for S-Chess, where
Maia cannot operate.

`tools/schess_candidate_proxy_audit.py` applies exactly this proxy to exported
Seirawan records without changing the website or generation data. The first
curated-set audit verified a gating move (`q57pn`, `f8b4h`) as the top candidate.
The curated difficulty labels are not yet suitable as a calibration target:
the first-move proxy ranks did not increase monotonically, and `cdkuv` is a
particularly useful disagreement (rank 30 despite its Beginner label). The
next work should use selected human judgements or future user solve data,
then refine candidate ordering from concrete disagreements rather than fitting
to the small curated levels.
## Threat and refutation module

The transferable candidate proxy now distinguishes a geometric attack from a
legal immediate capture. This mattered in the S-Chess regression case `cdkuv`:
a static map claimed that the Elephant on c5 could take `Rc1`, but Fairy/pyffish
reports no legal move to c1 after `Rc1`. Hanging-risk detection therefore uses
legal opponent replies.

Material threats now also include a *reinforced* attack: adding a second
attacker to an already attacked piece becomes a visible threat once attackers
outnumber defenders. This recognizes `Hb4` plus `Rc1` against the c5 Elephant.
The proxy additionally applies a shallow countercheck certificate to threat
moves. A countercheck only refutes a candidate when every legal check evasion
still permits capture of the moved piece on the next turn. Thus `Rd5 ...Ne3+`
is penalized in `cdkuv`, whereas `Rc1 ...Re1+` is not falsely rejected because
White has evasions that save the rook.

After these corrections `Rc1` improved from priority rank 30 to rank 5 in the
raw candidate list. It need not be forced to rank 1: the remaining checks and
captures are sensible early human candidates that can be rejected quickly.
The planned search metric should count those short rejections rather than
pretend that they were never considered. The countercheck probe is currently
more expensive than the base proxy, so the next implementation task is to
activate it only for the narrow candidate band that a human would actually
inspect.
### Threat-module calibration result

The narrowed countercheck-refutation probe was calibrated on the same grouped
500-puzzle Lichess benchmark. It improved the local S-Chess regression case
`cdkuv`, but did not improve global standard-chess rating prediction when its
penalty was folded directly into candidate attractiveness:

| Model | Before threat/refutation | After threat/refutation |
| --- | ---: | ---: |
| Candidate proxy only | 0.562 | 0.556 |
| Baseline + candidate proxy | 0.750 | 0.748 |
| Baseline + Maia + candidate proxy | 0.827 | 0.825 |

This does not invalidate legal attack, reinforced-threat, or persistent
countercheck detection. It says they should not yet be treated as a universal
probability penalty: a refuted forcing candidate is often a *quickly inspected
decoy*, which contributes a small search cost rather than making the solution
less likely to be noticed. The next model should preserve the threat/refutation
facts as separate visible-tree features: number of active decoys, whether they
are rejected in one reply, and whether the solution itself creates a certified
material threat. This separates candidate order from the cost of rejecting an
attractive alternative.
### Threat tree as separate search cost

The same 500-puzzle run was then re-evaluated without folding the
countercheck penalty into the candidate probability. `tools/threat_tree_features.py`
extracts four separate facts from the already stored active candidate band:
active material threats, countercheck-refuted decoys, their threatened material
value, and whether the supplied solution is a certified material threat.

| Model | Spearman | MAE |
| --- | ---: | ---: |
| Baseline + candidate proxy | 0.748 | 311.0 |
| Baseline + proxy + threat tree | 0.748 | 309.2 |
| Baseline + Maia + proxy | 0.825 | 261.3 |
| Baseline + Maia + proxy + threat tree | 0.825 | 258.7 |

So threat/refutation information is a modest calibration improvement (especially
MAE), but not yet a broad rank-order improvement. This is consistent with the
intended interpretation: a quickly refuted forcing move adds a small conscious
search cost rather than necessarily changing the relative difficulty category.
Keep it as a separate variants-tree cost in future S-Chess difficulty estimates.
## Human S-Chess policy-data prerequisite

A supervised human-move policy must use **only genuine human Seirawan games**;
self-play is excluded. `tools/build_chesscom_human_move_dataset.py` now emits
one FEN/selected-UCI row per decision and strictly accepts a source only when
its Chess.com `Variant` header explicitly identifies Seirawan/S-Chess.

A header audit of the current 6,817 root-level `chesscom_*.pgn4.txt` files found
6,800 `FFA` and 17 `Teams` wrappers, all with four-player/custom rules that
merely include `SeirawanSetup`. The strict extractor correctly rejects the test
sample. These files must not be used to train the policy model. Before the
policy project can proceed, obtain or fix a Chess.com export path that returns
an explicit two-player Seirawan variant header and validates against the
requested game ID. The existing extractor is intentionally fail-closed until
then.
## Initial S-Chess human-policy baseline

The genuine human corpus is now available locally at
`data/policy/chesscom_human_moves_full.jsonl`. At the first policy pass it
contained 728,372 usable decisions from 15,901 named players after excluding
opening plies. This corpus is distinct from self-play and is therefore suitable
for learning a *human candidate prior*.

`tools/train_schess_human_policy.py` is the first deliberately small baseline:

- Each selected human decision is paired with the played legal move and five
  deterministic random legal alternatives.
- Every candidate receives variant-aware signals already used by the project:
  forcing tier, check/capture value, certified material threat, simplification,
  immediate reply count, hanging cost, material context, and player experience.
- A gradient-boosted classifier is evaluated with a player-disjoint holdout,
  not a random row split.

Smoke result (500 sampled decisions, 480 usable; 94 unseen holdout players):

| Metric | Result |
| --- | ---: |
| ROC AUC | 0.702 |
| Average precision | 0.447 |
| Chosen move ranked first among six candidates | 54.4% |
| Random six-candidate baseline | 16.7% |
| Mean reciprocal rank | 0.701 |

This establishes that real human S-Chess choices contain learnable signal beyond
our hand-written forcing order. It does **not** yet tell us puzzle difficulty:
random alternatives make this ranking task too easy. The next experiment must
cache candidate feature rows and replace part of the random alternatives with
plausible forcing/quiet decoys, then evaluate the trained policy over complete
legal-move sets. The resulting policy probability and solution rank can become
features for the puzzle-difficulty model, while retaining the visible-tree
analysis for the continuation cost.

### Full-legal-move policy check

The sampled-alternative metric above is useful only as a quick smoke test. A
more realistic 500-decision player-disjoint run was therefore made with every
legal Seirawan move scored at each position (17,804 candidate rows; 480 usable
decisions; 114 holdout decisions). It produced:

| Metric | All positions | Opening, ply < 20 | Later positions |
| --- | ---: | ---: | ---: |
| Selected move ranked first | 43.9% | 33.3% | 48.7% |
| Mean reciprocal rank | 0.568 | 0.468 | 0.615 |
| Mean selected-move rank | 6.56 | 8.97 | 5.45 |
| Uniform random top-1 over all legal moves | 4.43% | 2.97% | 5.10% |

The model artifact is local at
`data/policy/human_policy_full_legal_500/human_policy_model.joblib`. The
opening result does not suggest that book-like early moves inflate the signal;
it is actually weaker in this small holdout. The 43.9% all-legal figure is the
relevant starting point for puzzle work. Its next use is to score every
candidate at each solver decision in an S-Chess puzzle and derive solution
rank, probability margin, and decoy mass as difficulty features.

### Rating-filter check

The corpus stores the mover's Chess.com variant rating, so the policy trainer now
supports `--min-elo`. A small 1600+ full-legal smoke test retained 221,148
eligible decisions, but its player-disjoint holdout was only 18 players / 40
decisions and achieved 30.0% top-1 versus the broader model's 43.9% on its own
500-decision test. This is not a conclusive quality comparison, but it does
show that aggressive rating filtering rapidly removes player diversity. Keep
the broad policy model as the present puzzle reference; revisit rating-specific
models only with larger cached full-legal samples and a fixed common holdout.

## Policy applied to puzzles

`tools/score_schess_puzzles_policy.py` applies a persisted policy model to each
solver move in a puzzle line and writes a separate research JSON. It stores
strict rank, tie size, expected tied rank, probability gap, normalized candidate
entropy, and aggregate line costs. Equal tree probabilities are deliberately
represented as a tie rather than falsely ordered by UCI text.

The first curated-set run is at
`data/complexity/schess_policy_puzzle_scores_curated.json`. It confirms that a
first-move rank alone is insufficient: some difficulties arise only in later
solver decisions and quiet positions often form broad policy ties. The useful
future features are therefore the complete decision sequence: accumulated rank
search cost, policy surprise relative to uniform legal moves, higher-ranked
decoys, and distribution entropy. These remain local research metadata until
they are calibrated well enough to expose.
