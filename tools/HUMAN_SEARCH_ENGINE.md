# Human Search Prototype

This local experiment estimates move-execution difficulty by constructing a small,
explicit search tree instead of combining static engine features.

## Current search model

- Legal move generation: pyffish with chess; no Fairy-Stockfish evaluation.
- Candidate ordering:
  1. checks, captures, and material threats;
  2. captured/threatened material;
  3. reduction in the opponent's legal moves, calculated only for a shortlist.
- Search: alternating selective minimax, currently depth 3 with up to 4 candidates
  per node for the first 30-puzzle probe.
- Static evaluation: material (without kings), immediately hanging material, check.
- Stopping certificates:
  - terminal position;
  - major material edge with little opponent forcing play;
  - quiet material conversion.

The reported human_search_nodes count is the number of positions this model actually
visits to make the puzzle decisions. It is the primary difficulty candidate.

## First probe

lichess_human_search_probe_30.json, depth 3, four candidates:

- Mean nodes per puzzle: 177.5
- Mean supplied-solution match rate: 0.714
- Spearman human search nodes vs Lichess rating: 0.511

This is only 30 samples and is not comparable yet to the old 500-puzzle models. It
does show that an explicit selective tree is viable and produces a directly inspectable
search effort.

## Known limits

- The tree still has a fixed depth and candidate cap. A useful certificate must replace
  more of this artificial horizon.
- Quiet moves are currently weakly represented. Add a small class of defensive,
  simplifying, and game-state-reducing candidates.
- The static evaluation does not recognize long tactical compensation, pawn races, or
  positional activity.
- A single confidence gap is recorded but does not yet prune siblings early.
- Opponent replies are selected with the same candidate policy; future work should
  compress equivalent defensive replies and retain only plan-changing replies.

## Next calibration loop

1. Inspect puzzles where visited-node count contradicts their Lichess rating.
2. Tune certificates and candidate classes from those concrete examples.
3. Add early pruning only when a candidate reaches a trustworthy terminal or
   conversion certificate.
4. Repeat on 100, then 500 profiles once runtime and behavior are stable.