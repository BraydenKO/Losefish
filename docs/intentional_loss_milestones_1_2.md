# Intentional Loss: Milestones 1-2 Implementation Notes

## Scope

This implementation stops after the requested correctness-reference milestones.
It does not add transposition-table use, Syzygy semantics, helper-thread search,
advanced pruning, quiescence search, or normal Stockfish move-ordering
heuristics to the loss objective.

## Architecture

`SearchObjective` identifies the objective independently of the tree-search
mechanics. `SearchObjectivePolicy` supplies:

- heuristic leaf conversion;
- draw utility;
- checkmate utility.

`LoseObjectivePolicy` is the first implementation. The reference alpha-beta
driver consumes the policy without embedding loss-specific terminal semantics in
its recursion. Future objectives can provide another policy; objectives needing
different node aggregation (for example probabilistic expectimax) can add a
different driver while retaining the same objective boundary.

Loss values are side-to-move-relative:

- being checkmated is large and positive;
- draw is zero;
- checkmating the opponent becomes large and negative after negamax sign
  conversion;
- a non-terminal leaf temporarily uses negated conventional NNUE, clamped
  outside decisive score ranges.

## Modified files

### `src/search.h`

**Why:** Defines the objective boundary and the public Milestone-2 verification
result. Declares the reference alpha-beta search, exhaustive oracle, and
loss-mode iterative deepening.

**Design relationship:** Separates value semantics from search mechanics through
`SearchObjectivePolicy`.

**Assumptions:** The first policy fits centered, side-to-move negamax values.
Probabilistic/non-zero-sum objectives may need a new aggregation driver.

**Still to validate:** API shape before adding further objectives; no ABI
stability is promised for this research option.

### `src/search.cpp`

**Why:** Implements `LoseObjectivePolicy`, single-thread iterative deepening,
unpruned alpha-beta negamax, and a separate exhaustive fixed-root-color minimax
oracle.

**Design relationship:** The alpha-beta search recursively models both colors
trying to lose. The oracle independently uses `max` on the original side's turns
and `min` on the opponent's turns, so it does not merely repeat the negamax sign
logic being tested.

**Assumptions:**

- loss > draw > win is represented by positive > zero > negative;
- earlier self-checkmate is preferred;
- negated NNUE is only a finite-horizon heuristic;
- legal move generation order is acceptable because no ordering optimization is
  claimed.

**Still to validate:**

- repetition with preserved game history;
- time, node, stop, and ponder edge cases;
- explicit loss-mode UCI score notation;
- deeper tactical fixtures distinguishing recursive loss search from root-only
  normal-score reversal;
- whether a dedicated loss evaluator eventually replaces `-NNUE`.

### `src/engine.cpp`

**Why:** Registers `IntentionalLoss` and implements the deterministic
`losscheck` test runner. The runner advances randomized legal walks from the
current FEN and compares alpha-beta with the exhaustive oracle.

**Design relationship:** Exposes the objective experimentally without changing
normal mode defaults. Validation orchestration remains outside search mechanics.

**Assumptions:** Sparse starting FENs keep the exhaustive depth-3 oracle small
enough for routine tests. Seed zero is normalized to one.

**Still to validate:** Broader randomized distributions and larger shallow test
corpora.

### `src/engine.h`

**Why:** Exposes the engine-level `loss_search_check()` validation entry point.

**Design relationship:** Keeps UCI parsing separate from validation execution.

**Still to validate:** Whether this temporary research API should remain public
after a dedicated unit-test target exists.

### `src/thread.cpp`

**Why:** Bypasses normal Syzygy root ranking when `IntentionalLoss` is enabled.

**Design relationship:** Normal tablebase ranks have the opposite utility and
would contaminate the reference result. The loss search itself does not start
helper workers.

**Assumptions:** Configuring `Threads > 1` is allowed, but loss mode uses only
the main worker.

**Still to validate:** Objective-aware Syzygy mapping and SMP are explicitly
deferred.

### `src/uci.cpp`

**Why:** Adds the non-UCI research command:

```text
losscheck <depth> <positions> <seed>
```

**Design relationship:** Provides a small automated correctness surface without
adding test-only behavior to the search algorithm.

**Assumptions:** Like existing debug commands, `losscheck` is not a standardized
UCI command.

**Still to validate:** Input bounds and friendlier errors for unreasonable
depths/counts.

### `tests/loss_search.py`

**Why:** Runs deterministic randomized legal walks from four sparse positions,
compares alpha-beta against exhaustive minimax on 96 resulting positions, and
checks checkmate/stalemate terminal values.

**Design relationship:** Establishes the Milestone-2 correctness gate before any
optimization is introduced.

**Assumptions:** Depth 3 gives useful recursive coverage while keeping exhaustive
search fast. The official NNUE file for this revision is available to the
binary.

**Still to validate:** More terminal motifs, recursive-vs-root-reversal fixtures,
repetition/fifty-move cases, promotions, castling, en passant, and sanitizer
builds.

### `docs/intentional_loss_design.md`

**Why:** Records the approved recursive objective, mathematical robustness
analysis, implementation strategies, hazards, and staged plan.

**Design relationship:** This remains the normative design document.

**Still to validate:** Items listed in its validation plan remain open unless
explicitly covered here.

## Validation performed

The following completed successfully on Windows with the MSYS2 MinGW toolchain:

```text
make ARCH=x86-64 COMP=mingw all
python tests/loss_search.py src/stockfish.exe
stockfish.exe bench 16 1 3 default depth
```

Observed oracle result:

```text
loss-search tests passed: 96 randomized positions,
alpha-beta == exhaustive oracle,
terminal semantics verified
```

Normal mode remained the default and completed the standard 51-position
depth-3 benchmark. A manual `Threads=4` loss-mode run returned a result using
only the main reference worker, as intended.

## Milestone gate

Milestones 1 and 2 are implemented. No optimization milestone has begun.

Before proceeding, review should focus on:

1. objective-policy boundaries;
2. terminal and mate-distance semantics;
3. independence of the fixed-color oracle;
4. whether the current randomized corpus is sufficient for the first gate;
5. adding a concrete recursive-vs-root-reversal fixture.

