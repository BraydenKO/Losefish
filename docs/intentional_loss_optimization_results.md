# Intentional-loss optimization results

## Scope

This optimization pass tested only exact search transformations. Selective
pruning, reductions, threading, Syzygy, and probabilistic approximations remain
disabled.

Every candidate was built in release mode and checked against:

- the permanent 12-position benchmark;
- complete optimal root move sets, not only the selected move;
- deterministic values and PVs;
- the independent exhaustive oracle;
- 96 randomized positions and seven semantic motif fixtures.

## Reference performance

The checked-in unoptimized baseline searches 871,700 timed nodes across the
default benchmark repetitions, with 197,500 cutoffs and an observed branching
factor of 8.52. Its short-tree NPS is approximately 8.6 million on the baseline
machine, although wall-clock results vary with scheduling and CPU power state.

## Experiment 1: captures and promotions first

Result: **rejected**.

The ordering was mathematically safe and passed the oracle, but it was a poor
heuristic for the loss objective:

- nodes increased by 13.4%;
- wall time increased by approximately 139% in the measured run;
- one tied Pauly-selfmate PV changed;
- values and complete optimal move sets remained correct.

This demonstrates why conventional Stockfish move-ordering assumptions cannot be
copied into loss search without measurement.

## Experiment 2: objective-aware transposition table

Result: **retained, correctness validated, performance mixed**.

The reference search now:

- XORs an intentional-loss namespace salt into TT keys so normal-search entries
  are not intentionally shared with loss-search entries;
- converts mate scores to and from root-relative form using Stockfish's existing
  mate-distance helpers;
- honors exact/lower/upper bound semantics under the loss-negamax value system;
- uses a legal TT move first for ordering;
- accepts a stored value cutoff only when the rule-50 clock is zero.

The last restriction is deliberately conservative. When the rule-50 clock is
zero, the immediately preceding move was irreversible, so earlier repetition
history cannot alter the node's result. At other nodes, a TT entry may suggest a
legal move, which cannot change minimax correctness, but its stored value is not
trusted. This avoids assuming that a board-only key captures path-dependent
repetition semantics.

Permanent benchmark result:

- Reference: PASS;
- behavior: identical;
- nodes: 797,900, an 8.5% reduction;
- TT hit rate: 8.40%;
- cutoffs: 184,700;
- observed branching factor: 8.82;
- measured shallow-tree NPS was 22% lower and wall time 17% higher in the final
  run because probing overhead exceeds the saved work at these depths.

The TT is retained because it provides exact reusable information and measurable
node reduction, while the benchmark clearly records that it is not yet a net
speed win on the shallow corpus.

Benchmark timing repetitions use distinct deterministic TT namespaces so the
same search is not artificially accelerated by entries left by an earlier timing
sample.

## Experiment 3: principal-variation search

Result: **rejected**.

Exact zero-window searches with full-window re-search passed every correctness
test. Combined with the TT they reduced nodes by 10.1% relative to the reference,
only 1.6 percentage points beyond the TT alone. Re-search and probing overhead
made wall time worse than the TT-only result, so the added complexity was removed.

## Experiment 4: loss-cutoff history ordering

Result: **rejected**.

A dedicated, objective-specific from/to history table was trained only from
loss-search cutoffs and used after the TT move. It remained mathematically exact,
but the permanent suite showed only an 8.8% node reduction relative to the
reference—essentially unchanged from the TT's 8.5%—while sorting overhead reduced
NPS and changed three tied PVs. The experiment was removed.

## Practical speed

Fresh-process start-position measurements for the retained TT implementation:

| Fixed depth | Wall time | Best move |
|---:|---:|---|
| 4 | about 1 ms | `a2a3` |
| 5 | about 2 ms | `a2a3` |
| 6 | about 12 ms | `a2a3` |
| 7 | about 27 ms | `a2a3` |
| 8 | about 0.54 s | `a2a3` |
| 9 | about 1.03 s | `a2a3` |

A depth-10 attempt did not complete within two minutes on the test machine.
This non-monotonic explosion is expected from an exact search with weak
objective-specific move ordering and no selective pruning. A five-second
`movetime` search responds correctly, but playing strength and horizon stability
should not yet be compared with normal Stockfish.

In practical terms, the engine is usable for experiments and short time controls,
but it remains a research reference rather than a strong real-time loss engine.

## Recommended next work

The next step should be to expand the performance corpus to deeper, non-oracle
timing positions.
The existing shallow corpus should remain the correctness gate; a separate deeper
corpus is needed to measure TT amortization without making exhaustive verification
impractical. Only then should another ordering representation be attempted; the
three ordering experiments above show that shallow-node savings alone do not
justify per-node machinery.
