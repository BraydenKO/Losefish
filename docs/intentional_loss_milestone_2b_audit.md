# Milestone 2b Correctness-Repair Audit

## Conclusion

Milestone 2b resolves the two blocking defects identified by the first formal
audit:

1. reference loss search no longer calls NNUE at a leaf, so an in-check horizon
   is valid;
2. reference loss search no longer reads `Worker::optimism`, initialized or
   otherwise.

The exhaustive oracle now independently encodes leaf perspective, draw value,
checkmate value, and fixed-color min/max backup. Verification requires both:

- equal root values; and
- identical complete sets of optimal legal root moves.

Both release and assertion-enabled debug builds pass the expanded suite. No
search optimization was introduced.

## 1. Deterministic reference evaluator

The reference search now uses:

```text
conventional_material(position, side_to_move)
    = non-pawn material(side_to_move)
    + PawnValue * pawns(side_to_move)
    - non-pawn material(other side)
    - PawnValue * pawns(other side)

loss_leaf = -conventional_material
```

Properties:

- deterministic;
- side-to-move-relative;
- defined in check;
- defined outside check;
- independent of NNUE;
- independent of accumulator state;
- independent of optimism;
- independent of histories;
- independent of TT state;
- clamped outside decisive mate/tablebase ranges.

This evaluator is intentionally weak as a chess heuristic. Its purpose is to
make the reference game tree well-defined and testable at every legal horizon,
not to make loss search strong.

### In-check verification

The suite includes an explicit depth-zero position where the side to move is in
check but has a legal evasion:

```text
FEN: 7k/8/6K1/8/8/8/8/7R b - - 0 1
Depth: 0
```

The old implementation would pass this position to `Eval::evaluate()`, violating
its `!pos.checkers()` assertion. The repaired implementation evaluates material
directly. The assertion-enabled debug build completes this fixture and the full
suite successfully.

## 2. Optimism independence

The complete call chain for reference leaves is now:

```text
reference_negamax()
  -> reference_material_eval()
  -> SearchObjectivePolicy::leaf()
```

It does not call:

```text
Worker::evaluate()
Eval::evaluate()
optimism[]
```

Normal Stockfish search continues using its unchanged NNUE/optimism path.
Therefore the repair is isolated to the experimental reference objective.

## 3. Oracle independence

The oracle no longer calls `LOSE_OBJECTIVE` for its semantics.

It independently specifies:

- repetition/fifty-move draw as `VALUE_DRAW`;
- stalemate as `VALUE_DRAW`;
- checkmated side loss value as `mate_in(ply)`;
- terminal conversion into fixed root-color perspective;
- its own duplicated material calculation;
- its own conversion from conventional material to side-to-move loss utility;
- `max` at root-color turns;
- `min` at opposite-color turns.

The reference search and oracle still necessarily share:

- legal move generation;
- `Position` make/undo;
- piece values;
- chess draw detection.

Those are rules/state primitives rather than the search semantics under test.
Duplicating them would create a second chess implementation and would not be a
practical correctness improvement.

## 4. Optimal-move-set comparison

Score equality alone permits an error where two algorithms return the same value
but disagree about which moves attain it.

Verification now performs an additional full-window pass over every legal root
move:

```text
alphaBetaOptimalMoves =
    all moves whose reference-negamax value equals the alpha-beta root value

oracleOptimalMoves =
    all moves whose fixed-color exhaustive value equals the oracle root value
```

Both sets are sorted by raw move encoding and compared for exact equality.
`LossSearchVerification::passed()` requires score equality and set equality.

The normal engine path does not perform this extra work. It exists only in the
`losscheck` diagnostic.

## 5. Terminal and mate-distance verification

The suite now uses exact assertions:

```text
already self-checkmated at root: +32000
Pauly forced selfmate at ply 4: +31996
stalemate: 0
```

The Pauly PV remains:

```text
1.c8=N e6 2.g8=B Bxg2#
```

This establishes the intended arithmetic:

```text
mate_in(0) = 32000
mate_in(4) = 31996
```

and demonstrates that the earlier terminal receives the larger favorable loss
value.

The mate-versus-stalemate fixture continues to select a zero-valued stalemate
instead of a negative opponent-checkmate result.

## 6. Verification results

The suite covers:

- 96 deterministic randomized sparse legal-walk positions;
- 7 motif fixtures;
- an in-check depth-zero leaf;
- forced selfmate;
- root checkmate;
- stalemate;
- mate-versus-stalemate;
- underpromotion;
- promotion alternatives;
- zugzwang-shaped quiet play;
- a perpetual-check seed;
- preserved-history threefold repetition;
- a position with one legal move.

Release build:

```text
make ARCH=x86-64 COMP=mingw all
python tests/loss_search.py src/stockfish.exe
```

Assertion-enabled debug build:

```text
make ARCH=x86-64 COMP=mingw objclean
make ARCH=x86-64 COMP=mingw debug=yes optimize=no all
python tests/loss_search.py src/stockfish.exe
```

Result:

```text
loss-search tests passed:
96 randomized positions,
7 motif fixtures,
scores and optimal move sets match exhaustive oracle,
recursive/terminal semantics verified
```

## 7. Source changes in Milestone 2b

### `src/search.cpp`

- Added the deterministic reference material evaluator.
- Added the independently expressed oracle loss-leaf evaluator.
- Removed reference/oracle calls to NNUE.
- Removed oracle dependence on `LOSE_OBJECTIVE` for draw, terminal, and leaf
  values.
- Enumerated and compared complete optimal root-move sets.

No pruning, TT cutoff, move ordering, threading, qsearch, or Syzygy feature was
added.

### `src/search.h`

- Extended `LossSearchVerification` with alpha-beta and oracle optimal-move
  sets.
- Strengthened `passed()` to require set equality.

### `src/engine.cpp`

- Extended diagnostic failure output to print both differing optimal-move sets.
- Normal UCI search behavior is unchanged by this diagnostic addition.

### `tests/loss_search.py`

- Added the explicit in-check depth-zero fixture.
- Strengthened mate-distance expectations to exact values.
- Updated success reporting to state optimal-set equivalence.

## 8. Remaining limitations

These are not blockers for the repaired reference semantics, but remain before
future production use:

- the material leaf is intentionally crude;
- `SearchObjectivePolicy` still models only value semantics, not expectimax
  backup;
- objective-aware UCI score reporting is absent;
- ponder/infinite behavior for loss mode remains incomplete;
- the oracle does not independently implement chess legality or repetition;
- deeper exhaustive coverage remains limited by combinatorial growth;
- fifty-move boundary, castling, and en-passant fixtures should be added before
  optimizing related code paths.

## 9. Audit decision

The shared leaf-evaluation defects from the first audit are resolved.

The reference loss-negamax and independent fixed-color exhaustive minimax now
agree on both values and complete optimal root-move sets over the current
verification corpus, including an assertion-enabled in-check horizon.

Milestone 2b is complete. Optimization remains intentionally paused pending
review.
