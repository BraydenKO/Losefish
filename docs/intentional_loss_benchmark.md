# Intentional-loss permanent benchmark

## Purpose

This benchmark is the gate for every future optimization of the intentional-loss
search. It compares the candidate engine with a checked-in reference baseline and
answers three separate questions:

1. **Correctness:** does alpha-beta still agree with the independent exhaustive
   oracle, and does it return the same value and complete set of optimal root moves?
2. **Behavior:** is the deterministic principal variation unchanged?
3. **Performance:** how did node count, NPS, search time, cutoffs, TT hits, and
   effective branching factor change?

The benchmark does not make an optimization acceptable merely because it is
faster. Any score or optimal-move-set mismatch is a hard failure and names the
exact fixture and expected/actual result.

## One-command use

From the repository root after building `src/stockfish.exe`:

```powershell
python tests\loss_benchmark.py src\stockfish.exe
```

The normal success summary has this form:

```text
Reference: PASS
Timing samples: 3 (per-position median)
Performance: nodes ... (...%), NPS ... (...%), search wall ... ms (...%)
Behavior: identical; cutoffs ...; TT hit rate ...; branching factor ...
```

Use `--samples` to increase timing samples and `--timing-runs` to increase the
amount of alpha-beta work in each sample. Correctness must remain deterministic
across every sample.

The reference baseline should be regenerated only for a deliberate semantic
change that has separately passed review:

```powershell
python tests\loss_benchmark.py src\stockfish.exe --write-baseline
```

Do not regenerate the baseline to hide a regression.

## Corpus

`tests/loss_benchmark_positions.json` is a named, deterministic corpus. It covers
the initial position, the Pauly selfmate, mate versus stalemate, a single legal
move, zugzwang, promotion choice, repetition history, sparse quiet and tactical
positions, balanced pawn play, a perpetual-check seed, and a terminal checkmate.
Each entry has tags so the corpus can later be grouped without changing the
runner.

The checked-in baseline is `tests/loss_benchmark_baseline.json`. It records the
source revision, values, complete optimal move sets, PVs, and all counters for
every named fixture. Keeping per-position data is what makes regression output
specific rather than merely reporting that an aggregate changed.

## Measurement semantics

- `nodes` counts nodes in the timed reference alpha-beta calls. The default
  benchmark repeats each call 100 times to reduce timer quantization and process
  startup noise.
- `oracle_nodes` is reported per correctness verification and is not part of the
  timed alpha-beta node count.
- `search wall` uses a monotonic microsecond-resolution clock around alpha-beta
  only.
- `NPS` is timed alpha-beta nodes divided by that search time.
- `cutoffs` counts alpha-beta bound cutoffs.
- `TT hit rate` is currently zero by construction; the counter is already part
  of the stable output contract for the TT milestone.
- `branching factor` is legal moves observed divided by expanded nonterminal
  nodes. It is an observed search-tree statistic, not a depth-root estimate.
- `verification wall` is harness time and includes the exhaustive oracle and
  optimal-root-set enumeration. It is useful for test-suite cost, not engine NPS.
- `depth reached` is the requested and completed reference depth and is checked
  per fixture.

Values, optimal move sets, oracle node counts, and PVs must be identical across
timing samples. Search counters and elapsed time use per-position medians because
TT replacement collisions can produce small counter differences without changing
the result.

Wall-clock and NPS measurements remain sensitive to CPU scheduling and power
state. Node reduction is therefore the primary performance signal for pruning
and move ordering; NPS is most useful for detecting implementation overhead when
node counts are equal. Larger or repeated runs should be used before claiming a
small speedup.

## Current reference result

The initial permanent baseline passes all 12 named fixtures:

- value and complete optimal move sets match the exhaustive oracle;
- deterministic PV behavior is identical;
- 871,700 timed nodes are searched across the default 100 repetitions;
- 197,500 alpha-beta cutoffs occur;
- observed branching factor is 8.52;
- TT hits are zero, as expected before TT support.

The broader correctness suite also passes 96 deterministic randomized positions
and seven motif fixtures.

## Guidance for optimization order

The baseline shows that alpha-beta already removes a large fraction of the
exhaustive tree on several fixtures, while broad quiet positions retain high
branching factors (20.43 at start position and 35.05 in the perpetual-check
seed). This makes **semantics-preserving move ordering** the lowest-risk first
experiment: ordering cannot alter minimax values or optimal move sets, but can
increase early cutoffs. It must still pass this benchmark because the selected
PV may change among tied optimal moves; such a PV change is reported as a
behavior change rather than a correctness failure.

A transposition table is the next high-value candidate because repeated and
perpetual structures are represented in the corpus and the TT-hit metric is
already wired. Re-enabling it requires objective-aware keys/bounds and explicit
proof that repetition and mate-distance state are represented correctly.

Selective pruning, reductions, threading, and Syzygy probing remain out of scope.
Their correctness arguments are substantially harder, and this suite should be
expanded with targeted fixtures before each is attempted.

## Files and assumptions

- `src/search.h` exposes verification results and counters. These are diagnostic
  data, not part of the objective policy.
- `src/search.cpp` instruments the unoptimized reference alpha-beta and uses a
  monotonic microsecond timer. Timing repetitions execute the same search from
  the same immutable root and do not affect the independent oracle.
- `src/engine.h`, `src/engine.cpp`, and `src/uci.cpp` expose the diagnostic
  `losscheck depth positions seed timing-runs` command. This remains a test
  interface, not normal move-selection behavior.
- `tests/loss_benchmark.py` owns baseline comparison, repeated timing, exact
  regression messages, and human-readable reporting.
- `tests/loss_benchmark_positions.json` owns the permanent corpus.
- `tests/loss_benchmark_baseline.json` owns the reviewed reference outputs.
- `tests/loss_search.py` accepts the added diagnostic field while retaining all
  prior semantic checks.

The suite assumes deterministic single-threaded reference search, a deterministic
leaf evaluator, and the current mate/draw value policy. A future intentional
semantic change requires a new audit and an explicitly reviewed baseline update.
