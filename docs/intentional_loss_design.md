# Adversarial Intentional-Loss Search: Design

## 1. Revised objective

This prototype models a recursive game in which both players deliberately pursue
their own loss:

- the **intentional-loss engine** tries to minimize its own eventual winning
  chances;
- the **opponent** actively tries to lose, and therefore tries to maximize the
  engine's eventual winning chances;
- after every future move, each player continues pursuing that objective.

Let `E` be the intentional-loss engine's color. In fixed-`E` terms, define a
utility `U(s)` such as the probability that `E` wins from position `s`. The
recursive objective is:

```text
U(s) = min U(child)    when E is to move
U(s) = max U(child)    when ~E is to move
```

Terminal values are:

```text
E wins:   high / +1
draw:     configurable, initially 0
E loses:  low / -1
```

This is not the previous "maximize the opponent's win probability against a
normal opponent" objective. In particular:

- the opponent does not choose normal strong moves;
- a root-only reversal is not sufficient;
- future intentional choices by both colors must be modeled recursively;
- move quality is defined by the equilibrium of the reversed-preference game,
  not by immediate centipawn loss.

It is also not randomness, `Skill Level`, negating a final root score, or choosing
the conventionally worst-looking move.

## 2. Key structural result: the game is still zero-sum

Although the preferences are unusual, they are exact opposites:

- `E` wants `U` smaller;
- `~E` wants `U` larger.

Therefore ordinary minimax and alpha-beta pruning remain mathematically
applicable. This is not a cooperative or general-sum game and does not require
expectimax.

It can also be represented in negamax form. Define `L(s)` as the value of
**the side to move eventually losing**. Every player maximizes `L`:

```text
L(s) = max(-L(child))
```

The sign change is valid because after a move:

- the child side losing means the parent side wins; and
- the parent side losing means the child side wins.

In a centered win/loss utility, those are negatives of one another. Thus the
shape of Stockfish's negamax recursion can be preserved:

```cpp
value = -search(child, -beta, -alpha, ...);
```

What must change is the meaning of every value entering that recursion:

- a conventionally bad position for the side to move must be good under the
  loss objective;
- being checkmated must be a favorable terminal result;
- checkmating the opponent must be unfavorable;
- tablebase wins and losses must be reversed;
- draw utility must be defined explicitly;
- pruning that relies on conventional chess-specific assumptions must be
  audited even where generic alpha-beta bounds remain sound.

This observation allows most of the search architecture to survive, but it does
**not** make a blind `return -Eval::evaluate(...)` patch correct.

## 3. Current Stockfish move-selection path

At repository revision `f4bcd404`, normal move selection is:

```text
UCI "go"
  -> UCIEngine parses limits and callbacks                  (uci.cpp, uci.h)
  -> Engine::go()                                          (engine.cpp, engine.h)
  -> ThreadPool::start_thinking()                           (thread.cpp, thread.h)
       generate legal root moves
       apply "searchmoves"
       rank root tablebase moves
       copy root state to workers
  -> Search::Worker::start_searching()                      (search.cpp, search.h)
  -> Search::Worker::iterative_deepening()
       aspiration windows
       MultiPV grouping
       repeated search<Root>()
       stable-sort RootMoves by descending score
       time-management decision
  -> Search::Worker::search<Root/PV/NonPV>()
       PVS/negamax alpha-beta
       qsearch at the horizon
       NNUE static evaluation
       TT cutoffs
       pruning, reductions, extensions, move ordering
  -> ThreadPool::get_best_thread()                          (thread.cpp)
  -> rootMoves[0].pv[0]
  -> UCI "bestmove"
```

### Normal value semantics

NNUE evaluation is side-to-move-relative. Positive means the side to move is
conventionally better. Search maximizes that score, negates child values, raises
alpha, and cuts off at beta. Mate and tablebase values use the same convention:
winning is positive and being mated is negative.

At the root, `RootMove::operator<` sorts scores descending. The highest normal
score becomes `rootMoves[0]`. In multi-thread mode,
`ThreadPool::get_best_thread()` votes using those scores and has special handling
for decisive values.

### Where the maximizing assumption appears

The zero-sum maximizing invariant is distributed throughout:

1. side-to-move NNUE evaluation;
2. `-search(child, -beta, -alpha, ...)`;
3. `bestValue = max(bestValue, value)`;
4. alpha updates and beta cutoffs;
5. qsearch stand-pat and tactical search;
6. mate-distance pruning and mate/stalemate returns;
7. TT lower/upper-bound semantics;
8. null-move, ProbCut, futility, razoring, singular extensions, and LMR;
9. history updates that reward fail-high moves;
10. root sorting, aspiration windows, time management, and best-thread voting;
11. Syzygy WDL/DTZ values and root ranking.

For the revised objective, generic "maximize the current value" control flow can
remain if the current value is redefined as side-to-move loss utility. Components
that assume positive means conventional chess strength require adaptation or
initially must be disabled.

## 4. Source-file inventory

### Direct control and selection

| File | Role |
|---|---|
| `src/uci.cpp`, `src/uci.h` | Parse `position`, `go`, limits, `searchmoves`, and options; emit search information and `bestmove`. |
| `src/engine.cpp`, `src/engine.h` | Own options, position, network, TT, and threads; dispatch `Engine::go()`. |
| `src/thread.cpp`, `src/thread.h` | Create legal root moves, initialize workers, run Lazy-SMP, and arbitrate the final worker. |
| `src/search.cpp`, `src/search.h` | Iterative deepening, `RootMove`, negamax/PVS, qsearch, terminal values, TT use, pruning, PV construction, and final selection. |

### Moves and position state

| File | Role |
|---|---|
| `src/movegen.cpp`, `src/movegen.h` | Legal, tactical, evasion, and capture move generation. |
| `src/movepick.cpp`, `src/movepick.h` | Search move ordering. |
| `src/position.cpp`, `src/position.h` | Move application, legality, checks, repetition, draws, keys, and SEE. |
| `src/history.h` | Move-ordering and correction histories. |
| `src/bitboard.cpp`, `src/bitboard.h` | Board and attack primitives. |
| `src/types.h` | Moves, values, mate/TB ranges, bounds, colors, and depths. |

### Evaluation and exact outcomes

| File | Role |
|---|---|
| `src/evaluate.cpp`, `src/evaluate.h` | Conventional side-to-move NNUE entry point. |
| `src/nnue/network.cpp`, `src/nnue/network.h` | NNUE loading and execution. |
| `src/nnue/nnue_accumulator.cpp`, `src/nnue/nnue_accumulator.h` | Incremental NNUE state. |
| `src/nnue/nnue_feature_transformer.h`, `src/nnue/nnue_architecture.h`, `src/nnue/layers/*` | NNUE inference internals. |
| `src/syzygy/tbprobe.cpp`, `src/syzygy/tbprobe.h` | Exact WDL/DTZ probing and root ranking. |
| `src/nn-89cb98a217f7.nnue` or configured `EvalFile` | Learned conventional leaf evaluation. |

### Search infrastructure

| File | Role |
|---|---|
| `src/tt.cpp`, `src/tt.h` | Store moves, values, evaluations, depths, and bounds. |
| `src/timeman.cpp`, `src/timeman.h` | Stop decisions based partly on score and best-move stability. |
| `src/ucioption.cpp`, `src/ucioption.h` | Option storage and parsing. |
| `src/misc.cpp`, `src/misc.h`, `src/numa.h` | Timing, synchronization, utilities, and worker/network placement. |

Tests, benchmark code, and build files do not decide a runtime move, but later
implementation should extend tests and may update benchmark expectations.

## 5. Exact search semantics

### Preferred representation

Use side-to-move loss utility because it matches Stockfish's negamax structure.
Call the mode `SearchObjective::Lose`, distinct from normal
`SearchObjective::Win`.

For non-terminal positions, the first proxy evaluator can be:

```text
loss_eval(position) = -normal_nnue_eval(position)
```

This is only a horizon heuristic. It says that a position NNUE regards as bad
for the side to move is promising for that side's goal of losing. The recursive
search - not the sign flip alone - then makes both players select moves that help
themselves lose.

### Terminal semantics

In normal Stockfish, no legal moves yields:

```text
in check:  mated_in(ply)   // very negative
not check: draw
```

In loss mode it must yield:

```text
in check:  loss_goal_achieved(ply)  // very positive
not check: configured draw utility
```

Conversely, a move that checkmates the child produces a very negative result
after negation, so the parent avoids giving mate when another line better
achieves its own loss.

Distance preference must also be chosen deliberately:

- a player trying to lose should normally prefer being mated sooner;
- if forced to win, it should prefer delaying that win;
- mate-score encoding and `value_to_tt()` / `value_from_tt()` must preserve
  these distance preferences.

The existing `mate_in()` and `mated_in()` names encode normal semantics and
should not be reused ambiguously. Objective-aware helpers are safer.

### Draw semantics

"Minimize winning chances" does not by itself specify the relative value of a
draw versus a loss. Recommended default:

```text
loss = +1, draw = 0, win = -1
```

from the side-to-move loss-utility perspective. This makes loss best, draw
second, win worst. A probability-only formulation where loss and draw are tied
would produce pathological draw seeking and should be a separate experimental
option, not the default.

Repetition noise in `value_draw()` should be disabled or made
objective-consistent for deterministic research runs.

### Tablebases

Syzygy results must be mapped into the loss objective:

- conventional side-to-move TB loss is the best result;
- TB draw is intermediate;
- conventional side-to-move TB win is worst.

Root `tbRank` ordering and `tbScore` cannot remain normal while loss search is
enabled. DTZ tie-breaking should prefer shorter paths to one's own loss and,
when forced to win, longer paths to that win, subject to the fifty-move rule.

### Transposition table

Alpha-beta bound mechanics remain valid in loss mode, but a normal-search TT
value is not interchangeable with a loss-search value. The mode must use:

- a distinct TT objective bit in the key/domain; or
- a cleared/separate TT when the objective changes.

TT move ordering can potentially share moves, but cached values, static
evaluations, bounds, and PV flags must not cross objective domains.

### Principal variation and UCI scores

PV construction can remain unchanged. UCI output must state what a score means.
For research clarity, loss-mode scores should be reported from the side-to-move
loss-objective perspective or exposed with an explicit info string. Silently
reporting them as normal centipawns would mislead GUIs and tests.

## 6. Does minimax already provide robustness?

### Worst-case robustness is automatic

Use fixed-engine utility `U`, where larger values mean a greater chance that
the intentional-loss engine `E` eventually wins. At an opponent node `o`,

```text
U(o) = max_a U(T(o, a))
```

because the opponent is trying to lose and therefore selects the reply most
likely to make `E` win. At an engine node `e`,

```text
U(e) = min_a U(T(e, a)).
```

For an engine candidate move `m`, define its opponent-reply vector:

```text
x_m = (U(T(T(e, m), r_1)), ..., U(T(T(e, m), r_n))).
```

The candidate's equilibrium value is:

```text
Q(m) = max_i x_m[i].
```

The engine selects `argmin_m Q(m)`. Consequently, it naturally avoids giving
the opponent even one effective opportunity to intentionally lose. If candidate
`A` has no opponent reply above `0.3`, while candidate `B` has one reply valued
`0.8`, the engine chooses `A` regardless of how many other replies under `B`
would make the engine lose.

This is robustness in the strict adversarial sense: minimize the worst reply.
It does not minimize the number of dangerous replies, maximize the number of
safe replies, or optimize the average reply.

### Example 1: reply counting can contradict the equilibrium

Suppose `-1` means `E` certainly loses, `0` is a draw, and `+1` means `E`
certainly wins:

```text
Engine move A -> opponent replies: [-1, -1, +1]
Engine move B -> opponent replies: [ 0,  0,  0]
```

Then:

```text
Q(A) = +1
Q(B) =  0
```

The recursive adversarial equilibrium chooses `B`. Although two of the three
replies after `A` make `E` lose, the opponent chooses the remaining `+1` reply.
A rule that maximizes the count or fraction of replies leading to `E`'s loss
would choose `A` and would be incorrect for the stated opponent model.

### Example 2: the number of dangerous replies is invisible to pure minimax

Consider:

```text
Engine move C -> opponent replies: [-1, +1]
Engine move D -> opponent replies: [-1, -1, -1, +1]
```

Both have equilibrium value `+1`, because the opponent has at least one reply
that makes `E` win:

```text
Q(C) = Q(D) = +1.
```

Pure minimax is indifferent. A reply-count secondary objective prefers `D`
because three replies, rather than one, still lead to `E` losing. This preference
does not improve the exact equilibrium result: an adversarially optimal opponent
selects `+1` in either position. It only makes the policy more tolerant of an
opponent that searches imperfectly, breaks ties differently, or occasionally
fails to find its best losing move.

### Example 3: a smoother position can still be worse in minimax

Let values be engine win probabilities:

```text
Engine move E -> [0.05, 0.05, 0.40]
Engine move F -> [0.30, 0.30, 0.30]
```

Minimax chooses `F` because `0.30 < 0.40`. A mean or threshold-count objective
could prefer `E`, but that assumes a distribution over opponent errors. Under
the exact adversarial model, the opponent always selects the `0.40` reply.

### Opportunity count is not strategically invariant

Raw legal-move counts are especially problematic:

- transpositions can represent strategically identical replies several times;
- one position may have many irrelevant king moves and another only forcing
  moves;
- promotions create several legal actions with closely related outcomes;
- search depth can split or merge apparent opportunities;
- counting treats a trivial-to-find reply and an obscure reply equally.

Thus "fewer opportunities for the opponent to lose" should not be inferred from
branching factor. The equilibrium cares about the best value the opponent can
attain, not how many syntactically distinct ways attain it.

### When an explicit secondary objective is useful

Reply robustness is useful only if at least one of the following is intended:

1. the opponent is bounded, noisy, or search-limited rather than exact;
2. search values are approximate and the top reply may be mis-ranked;
3. several engine moves are equal within the resolution of the primary search;
4. deterministic tie-breaking should prefer positions resilient to model error.

For the current exact adversarial specification, robustness should be
**lexicographic and secondary**, never a weighted term allowed to override a
real minimax difference.

Recommended comparison:

```text
1. minimize equilibrium value Q(m);
2. among moves equal within an explicit primary tolerance, maximize robust loss
   mass R(m);
3. use deterministic conventional tie-breakers.
```

For an exact reference search, the tolerance should be zero. For finite-depth
NNUE search, a small documented tolerance can represent score uncertainty, but
changing it changes the effective objective and must be reported in experiments.

A possible secondary statistic is:

```text
R_tau(m) = sum_i w_i * I[x_m[i] <= tau]
```

where `tau` is a loss/draw threshold and weights sum to one. Uniform `w_i`
measures reply fraction, not raw count. A future bounded-opponent model can
supply meaningful `w_i = P(r_i | position)`. Alternatives include a lower
quantile, expected value, or soft maximum:

```text
softmax_tau(x) = tau * log(sum_i w_i * exp(x_i / tau)).
```

Those alternatives are not exact minimax. They define a noisy or
risk-sensitive opponent model and should be exposed as separate research modes,
not silently mixed into the reference equilibrium.

### Recommendation for the first implementation

Do not add reply-count robustness to the recursive value or alpha-beta bounds.
Implement exact loss-negamax first. Record, for diagnostics:

- the best opponent reply value;
- the gap between the best and second-best opponent replies;
- the number/fraction of replies within a score band of the best;
- the number/fraction below configured loss and draw thresholds.

After correctness is established, an optional root tie-breaker may use these
statistics lexicographically. It should never alter a move with a strictly
better exact minimax value. This preserves the requested game while making
bounded-opponent experiments possible later.

## 7. Implementation strategies

### Strategy A: Root-only reverse selection

Run normal Stockfish and select its lowest normal root score.

**Runtime:** approximately `K` root PV searches for `K` comparable candidates;
all legal moves can approach 20-40x worst-case before TT reuse.

**Correctness:** wrong objective. Normal subtrees assume both future players try
to win. It neither models the opponent trying to lose nor future recursive
intentional choices.

**Use:** diagnostic baseline only.

### Strategy B: External recursive wrapper over normal searches

Build a shallow policy tree outside `Worker::search()`:

- at every node, enumerate a candidate set using normal search;
- recursively choose according to the loss objective;
- use normal NNUE/search at the policy horizon.

**Runtime:** approximately `K^d` leaf searches for branching `K` and policy depth
`d`, reduced somewhat by caching.

**Merits:** isolates experimental semantics and avoids touching core pruning.

**Problems:** extremely expensive, candidate generation is biased toward normal
winning moves, and shallow policy horizons cause severe horizon effects.

### Strategy C: Separate clean loss-negamax

Implement a new, correctness-first negamax search for `SearchObjective::Lose`
using:

- legal move generation;
- loss-oriented terminal and draw values;
- negated conventional NNUE at leaves;
- alpha-beta/PVS;
- objective-separated TT;
- iterative deepening and basic TT/capture ordering;
- initially conservative or disabled chess-specific pruning.

Normal `Worker::search()` remains untouched. Shared primitives are reused, while
loss search has explicit value semantics.

**Runtime:** with alpha-beta and basic ordering, likely 2x-10x slower at a given
depth than tuned Stockfish. It may reach several plies less under the same time
limit. Exact cost depends heavily on ordering after preference reversal.

**Merits:** correct recursive objective, low risk to normal Stockfish, clear
experiments, and a trustworthy reference implementation.

**Problems:** duplicates some orchestration and initially gives up many tuned
pruning gains.

### Strategy D: Objective-parameterized Stockfish search

Generalize the existing search with a compile-time or runtime objective:

```cpp
template<SearchObjective objective, NodeType nodeType>
Value search(...);
```

Preserve generic negamax/PVS machinery while routing:

- leaf evaluation;
- terminal and draw values;
- mate-distance handling;
- tablebase mapping;
- TT domain;
- score display;
- objective-safe pruning and ordering.

Pruning should be enabled incrementally after proof or testing. Generic
alpha-beta, aspiration windows, PVS, TT bounds, and LMR mechanics may be
structurally reusable; their chess-tuned conditions and margins are not
automatically valid under reversed preferences.

**Runtime:** potentially near normal Stockfish after substantial adaptation and
tuning. The first safe version, with suspect pruning disabled, may be 2x-10x
slower at equal depth or much shallower at equal time.

**Merits:** maximum reuse and the cleanest eventual architecture.

**Problems:** broad change surface. A missed normal-score assumption can create
plausible but incorrect results.

### Strategy E: Dedicated learned loss-position evaluator

Train an evaluator for the reversed-preference equilibrium rather than using
`-NNUE` as a horizon proxy. Generate data through loss-search self-play and
train on game outcomes or backed-up search values.

**Runtime:** inference can be comparable to NNUE, but data generation and
training are substantial. Search runtime depends on network architecture.

**Merits:** reduces horizon mismatch and learns motifs specific to forcing one's
own loss while the opponent resists by trying to lose.

**Problems:** requires a correct reference search first, large data generation,
and careful avoidance of circular labeling errors.

## 8. Recommendation

Implement **Strategy C first: a separate correctness-first loss-negamax**, then
use it as the oracle for migrating safe components into Strategy D.

This recommendation replaces the previous root-policy recommendation. A
root-level policy cannot represent the revised recursive opponent.

The separate search should preserve:

- board representation and legal move generation;
- make/undo and repetition state;
- incremental NNUE machinery;
- the negamax sign/window transform;
- generic alpha-beta/PVS;
- iterative deepening;
- a separate or objective-keyed TT;
- basic move ordering;
- threading only after single-thread correctness.

It should initially avoid or disable:

- normal root Syzygy ranking until reversed mapping is implemented;
- null-move pruning;
- conventional futility/razoring/ProbCut;
- singular extensions based on normal TT expectations;
- correction-history assumptions;
- normal Skill handling;
- normal best-thread score voting;
- conventional mate-distance helpers where semantics are ambiguous.

This changes more code than a root swap but is the smallest defensible approach
that actually computes the requested game.

## 9. Smallest modification set

A practical first implementation will likely touch:

1. **`src/search.h`**
   - add `SearchObjective`;
   - declare the loss-search entry points and objective-aware score helpers;
   - store mode/configuration on each worker.
2. **`src/search.cpp`**
   - implement iterative deepening and recursive loss negamax;
   - invert leaf evaluation only within that mode;
   - implement loss terminal/draw/mate-distance semantics;
   - select and output the loss PV.
3. **`src/engine.cpp`**
   - add an experimental UCI option such as `IntentionalLoss`.
4. **`src/thread.cpp`**
   - dispatch the correct search;
   - prevent normal Syzygy root ordering from overriding loss semantics;
   - initially constrain loss mode to one thread or add objective-aware worker
     arbitration.
5. **`src/tt.h`, possibly `src/tt.cpp`**
   - separate normal and loss objective TT domains.
6. **`src/syzygy/tbprobe.cpp` / `.h`**
   - required when exact tablebase support is enabled in loss mode; this can be
     deferred by disabling TB probing for the first prototype.
7. **`src/uci.cpp`**
   - only if loss score reporting needs a distinct UCI representation or
     explanatory info output.

The absolute minimum reference prototype can use `search.h`, `search.cpp`,
`engine.cpp`, and `thread.cpp`, run single-threaded, clear TT on mode changes,
and disable Syzygy in loss mode. That is preferable to prematurely modifying TT
and tablebase internals.

No NNUE network file needs modification for the first prototype.

## 10. Correctness hazards

- Negating NNUE is only the leaf heuristic; it does not by itself implement the
  recursive game.
- Normal mate values must not leak into loss terminal handling.
- A normal TT hit in loss mode is semantically invalid even if the board key is
  identical.
- Root sorting is reusable only after `RootMove::score` consistently means loss
  utility.
- Normal tablebase ranking will select exactly the wrong WDL class.
- Draws need a stable utility and objective-aware repetition handling.
- Pruning correctness and pruning strength are different questions. Alpha-beta
  remains sound, but chess-specific forward pruning can become unsound after
  reversing value semantics.
- Conventional move ordering will often search undesirable loss moves late,
  degrading alpha-beta efficiency without changing correctness.
- `Skill Level` and loss mode must be mutually exclusive.
- Multi-thread voting must compare loss-objective values, not normal values.
- UCI mate and centipawn output must not falsely claim conventional score
  semantics.
- Fifty-move and repetition rules are part of the game outcome, not merely
  search heuristics.

## 11. Validation plan

### Reference correctness

1. Implement a tiny unpruned minimax oracle for low depths.
2. Compare loss-negamax scores and best moves against it on randomized legal
   positions.
3. Verify alpha-beta on/off gives identical results.
4. Verify TT on/off gives identical results.

### Terminal fixtures

Test:

- a side able to allow mate in one;
- a side able to give mate in one but with an alternative;
- forced conventional wins and forced conventional losses;
- stalemate;
- repetition;
- fifty-move draws;
- underpromotion and self-stalemate motifs;
- mirrored/color-swapped positions.

Expected behavior includes preferring one's own forced loss, avoiding
checkmating the opponent when possible, and choosing a draw over a forced win
under the recommended utility ordering.

### Recursive distinction

Construct positions where:

- the normal worst root move fails because the opponent can intentionally avoid
  winning and instead force its own loss;
- a superficially good normal move eventually forces the engine's loss under
  reversed recursive play;
- root-only reversal and full loss-negamax choose different moves.

These fixtures are essential because they prove the implementation is not just
"bad Stockfish."

### Regression and performance

- Mode off must retain Stockfish's benchmark signature and best moves.
- Mode on must obey legality, `searchmoves`, stop, ponder, and time limits.
- Record nodes, depth, branching, TT hit rate, and wall time.
- Add pruning features one at a time and compare every shallow result with the
  unpruned oracle.
- Add tablebases only after WDL/DTZ reversal tests pass.
- Add SMP only after deterministic single-thread behavior is stable.

## 12. Staged roadmap

1. Formalize score constants and draw/mate-distance policy.
2. Add a single-thread, unpruned loss-negamax reference search.
3. Add iterative deepening, PVs, and deterministic UCI output.
4. Add an objective-separated TT.
5. Add basic loss-oriented move ordering.
6. Add reversed Syzygy semantics.
7. Audit and enable PVS, aspiration windows, LMR, and safe pruning individually.
8. Add objective-aware multi-thread arbitration.
9. Generate self-play data for a dedicated loss evaluator.
10. Consider merging the reference search into an objective-parameterized
    shared search only after equivalence tests are comprehensive.

The governing rule is that every optimization must preserve the recursive
min/max equilibrium. Conventional move quality is neither the target nor a
valid shortcut for it.
