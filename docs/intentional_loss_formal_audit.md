# Formal Audit of the Reference Intentional-Loss Search

## Executive conclusion

The recursive backup rule is mathematically correct for the intended game, and
the independent fixed-color oracle agrees with alpha-beta on the expanded test
set. However, the implementation is **not yet approved for optimization**.

Two blocking leaf-evaluation defects can make the alpha-beta search and oracle
agree on the same invalid value:

1. `reference_negamax()` calls NNUE at depth zero even when the side to move is
   in check, but `Eval::evaluate()` asserts that the position is not in check.
2. the reference path calls `Worker::evaluate()`, which supplies
   `optimism[pos.side_to_move()]`; loss iterative deepening never initializes
   `optimism`.

Release builds disable the first assertion, and both verification algorithms
share the same evaluator, so the current equality tests cannot detect either
problem. These defects must be corrected and revalidated before any
optimization is introduced.

The audit also finds that the current `SearchObjectivePolicy` abstraction is
adequate for alternate zero-sum negamax value semantics, but not for future
probabilistic human models. Those models need a different backup operator
(expectation or risk aggregation), not merely different leaf and terminal
values.

## 1. Mathematical semantics

Let `E` be the color controlled by the intentional-loss engine and let fixed
color utility `U(s)` increase with `E`'s chance of winning:

```text
U(s) = min U(child), when E is to move
U(s) = max U(child), when ~E is to move
```

The implementation instead stores `L(s)`, the utility of the **side to move
eventually losing**. With centered win/loss values:

```text
L(s) = -L(child)
L(s) = max over legal children
```

At an `E` node, maximizing `E`'s loss utility minimizes `U`. At an `~E` node,
maximizing `~E`'s loss utility maximizes `U`. Therefore side-to-move negamax is
algebraically equivalent to the required fixed-color min/max recurrence.

### Independent oracle mapping

The exhaustive oracle keeps root-color loss utility fixed:

```text
root color to move:       maximize root loss utility
opposite color to move:   minimize root loss utility
```

At a leaf, side-to-move loss utility is negated when the side to move is not the
root color. This is an independent backup formulation of the same game and is a
good structural cross-check of negamax signs.

## 2. Line-by-line semantic audit

Line numbers refer to the audited working tree and may move after later edits.

### Objective policy (`src/search.cpp`, `LoseObjectivePolicy`)

| Code | Audit |
|---|---|
| `objective() -> Lose` | Correct label, but currently unused by dispatch or assertions. A mismatched policy could be passed without detection. |
| `leaf(eval) -> clamp(-eval)` | Algebraically correct as a temporary quiet-leaf heuristic: conventional advantage for the side to move becomes disadvantage under its loss objective. It is not a learned estimate of the reversed game. |
| leaf clamp | Correctly prevents a heuristic leaf from impersonating an exact mate/TB result. |
| `draw() -> 0` | Correct for the documented ordering loss > draw > win. It does not represent a probability-only objective where draw and loss tie. |
| `checkmated(ply) -> mate_in(ply)` | Correct: being checkmated is favorable, and smaller `ply` gives a larger value, so earlier self-mate is preferred. |

### Dispatch and root terminal handling (`Worker::start_searching()`)

| Code | Audit |
|---|---|
| `accumulatorStack.reset()` | Required for incremental NNUE and correct. |
| non-main worker branch before objective dispatch | Safe only because the loss branch never starts helper workers. If a helper is accidentally started, it executes normal Stockfish search. This should eventually be guarded explicitly. |
| normal time-manager initialization | Reused. It is not part of the game-theoretic backup, but its normal score-stability assumptions are not used by loss search. |
| `tt.new_search()` | Semantically inert because loss search never probes or writes TT. It should be removed from loss dispatch for clarity, but does not change results. |
| no-legal-move root score | Correctly reverses root checkmate to `+VALUE_MATE` in loss mode and leaves stalemate at zero. It bypasses the objective policy and duplicates semantics. |
| `callsCnt = 0` | Initializes normal periodic stop checking. Safe for bounded searches. |
| no helper-thread start | Correct Milestone-1 single-thread behavior. `Threads > 1` remains configured but unused. |
| immediate bestmove after loss search | Correct for `go depth`. Incorrect UCI behavior for `ponder` or `infinite`: normal search waits for `stop`, loss search does not. |
| ponder from loss PV | PV propagation is valid. No TT ponder extraction occurs. |

### Reference alpha-beta (`reference_negamax()`)

| Code | Audit |
|---|---|
| `pv.clear()` | Correct for constructing the best continuation at this node. |
| stop returns zero | The returned value is not a valid bound, but callers detect `threads.stop` and discard the incomplete root iteration. Safe in the present call graph; unsafe if reused without that convention. |
| `check_time()` | Does not alter minimax semantics when the last completed iteration is retained. It uses Stockfish's normal time infrastructure but not normal evaluation-stability logic. |
| `if (ply && pos.is_draw(ply))` | Correctly applies repetition/fifty-move draws below root. Root draw claims are intentionally not terminal because a root move must still be supplied, matching Stockfish's existing convention. |
| legal move generation before depth test | Correct and essential: mate/stalemate at the horizon must override heuristic evaluation. |
| no legal moves + check | Correctly returns favorable self-checkmate. |
| no legal moves + no check | Correctly returns draw zero. |
| depth-zero `objective.leaf(evaluate(pos))` | **Blocking defect:** `evaluate()` is invalid in check. It also uses uninitialized/stale `optimism`. |
| `best = -infinity` | Correct because every side maximizes its own loss utility. |
| `do_move()` / `undo_move()` | Legality was already established. Incremental accumulator push/pop and state restoration are appropriate. TT prefetch inside `do_move()` is semantically inert. |
| `value = -search(child, -beta, -alpha)` | Correct negamax transform for centered side-to-move loss utility. |
| `value > best` | Correct: the current player chooses the continuation maximizing its own loss. |
| PV update | Correct for the strictly best value. Equal values retain deterministic legal-generation order. |
| `alpha = max(alpha, value)` | Correct lower-bound update. |
| `alpha >= beta` cutoff | Mathematically sound for zero-sum negamax with exact terminal/leaf values. |

### Fixed-color exhaustive oracle (`brute_force_loss_minimax()`)

| Code | Audit |
|---|---|
| draw and terminal detection order | Matches reference negamax. |
| terminal sign conversion | Correct: root-side checkmate is positive root-loss utility; opponent checkmate is negative. |
| leaf sign conversion | Correct fixed-color conversion of side-to-move loss utility. |
| root side `max`, opponent side `min` | Exactly matches the intended recurrence after changing from engine-win utility to engine-loss utility. |
| no cutoff | Correct exhaustive oracle. |
| shared policy/evaluator | Weakens independence. A policy or leaf bug can affect both algorithms identically. Terminal constants and a test evaluator should be independently specified in the oracle. |
| score-only equality | Insufficient when several moves share a score. Oracle PV or the complete optimal-move set should also be compared. |

### Loss iterative deepening

| Code | Audit |
|---|---|
| depths increase by one ply | Correct. |
| root candidates are all legal/searchmoves-filtered moves | Correct. |
| root `alpha` and child window `[-infinity, -alpha]` | Correct root alpha-beta formulation. A non-improving move may return only a bound, but it cannot become the selected best move. |
| retain only completed iteration | Correct stop safety. |
| descending `RootMove` sort | Correct because root score is root side's loss utility and larger is preferred. |
| reuse initial root order each iteration | Correct but intentionally slow; no previous-iteration ordering is used. |
| `maximumDepth` fallback | For ordinary timed searches it relies on stop checks. `infinite` and ponder behavior is incomplete as noted above. |

### Verification harness

| Code | Audit |
|---|---|
| validation disables time checks | Correct for deterministic exhaustive comparison. |
| source position searched and fully undone | Preserves the pre-root state chain, allowing repetition-history tests. |
| accumulator reset between algorithms | Correct. |
| alpha-beta and oracle share the worker | Convenient, but shares uninitialized `optimism` and the same NNUE adapter. |
| randomized legal walks | Useful coverage and deterministic by seed. They are not uniform samples of legal positions. |
| exact position at index zero | Correct diagnostic behavior. |

## 3. Stockfish assumptions still leaking into the reference path

1. **NNUE quiet-position precondition.** Normal search avoids raw static
   evaluation in check; the reference search does not.
2. **Optimism initialization.** Normal iterative deepening sets both optimism
   entries before searching a PV. Loss iterative deepening does not.
3. **Rule-50 damping.** Normal NNUE output is damped as the fifty-move counter
   grows. Negating it inherits this conventional heuristic. It is not proven to
   estimate loss-game outcomes.
4. **`Position::is_draw()` semantics.** The reference adopts Stockfish's
   claim/repetition handling and graph-history conventions. These are chess-rule
   semantics, but path-dependent TT reuse will require special care later.
5. **Normal time manager.** Initialization and periodic stop machinery are
   reused, while loss-mode ponder/infinite behavior is incomplete.
6. **Normal `RootMove` score vocabulary.** Fields such as `uciScore`,
   `scoreLowerbound`, and `averageScore` were designed for normal output. Only a
   subset is currently used.
7. **Normal UCI score interpretation.** Loss search emits no objective-aware
   score line. If normal PV output were enabled, positive mate would be displayed
   as the engine mating the opponent, which is the opposite meaning.
8. **Normal move application wrapper.** It prefetches TT and references shared
   history even though the reference search does not use either. This is harmless
   but obscures the dependency boundary.
9. **Normal mate score constants.** The arithmetic is reusable, but names such as
   `mate_in()` describe conventional semantics and make the reversed use easy to
   misunderstand.

## 4. Adversarial fixtures

### Fixture A: Pauly selfmate in two

```text
FEN: KB3N2/P1P1p1P1/5P1k/4P2p/7P/8/6B1/7b w - - 0 1
Depth: 4 plies
Loss PV: 1.c8=N e6 2.g8=B Bxg2#
Loss score: +31996
```

This is the classic Wolfgang Pauly selfmate. The published solution explains
that only `1.c8=N!` forces Black to mate White against Black's resistance; after
`1...e6`, only `2.g8=B` removes Black's alternatives and forces `2...Bxg2#`.
The source also shows why `1.g8=N#` is exactly wrong: it checkmates Black.
[Selfmate example and solution](https://en.wikipedia.org/wiki/Selfmate)

Recursive reasoning:

```text
White (engine) chooses c8=N to maximize White-loss utility.
Black chooses e6 rather than immediate Bxg2#, because Black tries to lose.
White chooses g8=B, which leaves Black no non-mating defense.
Black is forced to play Bxg2#, checkmating White.
```

Why the baselines differ:

- **Root-only reverse normal Stockfish:** normal MultiPV at depth 4 assigns many
  moves a normal `mate -1`, because normal Black willingly mates White. It does
  not model Black's `...e6` resistance and cannot identify the forcing
  underpromotion for the right reason.
- **Immediate conventionally worst move:** several moves appear to hang White
  to `...Bxg2#`; they fail once Black actively avoids mating White.
- **Leaf-only evaluation negation:** it cannot see the four-ply forced terminal
  and has no reason to select the exact knight-then-bishop promotion sequence.
- **Full recursive negated side-to-move utility:** with reversed terminal
  semantics, this is not a different algorithm; it is algebraically the same
  loss-negamax game. The meaningful contrast is with a mere leaf sign flip or
  with retaining normal mate semantics.

This fixture simultaneously covers recursive resistance, underpromotion,
avoidance of delivering mate, and forced self-checkmate.

### Fixture B: choose stalemate instead of delivering mate

```text
FEN: 7k/8/4Q1K1/8/8/8/8/8 w - - 0 1
Depth: 1-2 plies
Loss PV: 1.Qa2
Loss score: 0
```

White has moves that checkmate Black, but `1.Qa2` stalemates Black. Delivering
mate returns a large negative root loss value after negation; stalemate returns
zero. The search therefore chooses the draw. This demonstrates both draw utility
and avoidance of checkmating the opponent when a better loss-objective result
exists.

It also distinguishes loss search from a naive “negate NNUE only” patch that
leaves normal terminal mate/stalemate handling untouched.

### Fixture C: already checkmated

```text
FEN: 7k/6Q1/6K1/8/8/8/8/8 b - - 0 1
Loss value: +32000 at root
```

Black has no legal move and is in check. In loss semantics this is the best
possible result for Black, not a negative normal mate score.

### Fixture D: only one legal move

```text
FEN: 7k/8/6K1/8/8/8/8/7R b - - 0 1
Depth-4 PV: 1...Kg8 2.Rh8+ Kxh8 3.Kh6
```

Black begins in check and has exactly one legal move, `Kh8-g8`. Both alpha-beta
and exhaustive minimax must traverse that move; no objective can change legal
necessity. This validates evasion generation and make/undo behavior, while also
exposing the in-check horizon defect if the test is stopped at an unfortunate
depth.

### Fixture E: repetition opportunity with real history

```text
position startpos moves
g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1

Depth-2 loss PV: 1...Ng8
Loss score: 0
```

`...Nf6-g8` recreates the initial position for the third time. The verification
harness now searches the live `Position` with its pre-root state chain rather
than reconstructing from FEN, so the draw is observed by both algorithms.

### Fixture F: zugzwang-shaped pawn ending

```text
FEN: 8/8/8/3k4/3P4/3K4/8/8 b - - 0 1
Depth-4 PV: 1...Kd6 2.Kc3 Kc6 3.Kb2
```

This is not claimed as a tablebase proof. Its purpose is to ensure exhaustive
backup includes quiet king/pawn moves where passing would materially change the
position. It is a regression guard against later stand-pat, null-move, and
futility assumptions.

### Fixture G: promotion choice

```text
FEN: 7k/P7/6K1/8/8/8/8/8 w - - 0 1
Depth-3 PV: 1.a8=N+ Kg8 2.Kf6
```

All four promotions are generated and exhaustively compared. The current
horizon heuristic selects the knight promotion. This is a move-generation and
oracle-equivalence fixture, not an assertion that `-NNUE` is a correct long-term
loss evaluator.

## 5. Terminal and mate-distance proof

Let `M = VALUE_MATE` and terminal self-checkmate at root-relative ply `p` return:

```text
T_self(p) = M - p.
```

If two continuations force the current/root side to be checkmated at
`p1 < p2`, then:

```text
T_self(p1) = M - p1 > M - p2 = T_self(p2).
```

Because the root maximizes loss utility, it prefers the earlier self-mate.

If the opponent is checkmated at odd ply `p`, negamax propagation gives the
root:

```text
T_opponent(p) = -(M - p).
```

For `p1 < p2`:

```text
-(M - p1) < -(M - p2).
```

Therefore, when forced to mate the opponent, the root prefers the later mate.
This is exactly the documented distance policy.

The Pauly fixture realizes positive self-mate distance (`+31996`, mate at ply
4). The mate-or-stalemate fixture demonstrates that zero draw utility outranks
any negative opponent-mate value. Direct unit assertions over two different
mate distances should still be added after terminal semantics are factored into
an independently testable value-policy module.

## 6. Expanded reference verification

The automated suite now covers:

- 96 deterministic randomized legal-walk positions from sparse seeds;
- the Pauly forced selfmate and two underpromotions;
- an already checkmated position;
- an already stalemated position;
- mate-versus-stalemate choice;
- a quiet zugzwang-shaped pawn ending;
- all promotion choices;
- a published perpetual-check position;
- a true threefold-repetition opportunity with preserved history;
- a position with exactly one legal evasion.

The perpetual-check seed is a published game position commonly used for
perpetual-check training.
[Perpetual-check FEN source](https://www.chessworld.net/perpetual-check.asp)

Current result:

```text
loss-search tests passed:
96 randomized positions,
6 motif fixtures,
alpha-beta == exhaustive oracle,
recursive/terminal semantics verified
```

This result verifies backup equivalence for the values actually supplied to both
algorithms. It does **not** clear the shared leaf-evaluator defects identified
above.

Still missing:

- a debug/assertion build that reaches every horizon-in-check case;
- independent deterministic leaf evaluation valid in check;
- oracle optimal-move-set comparison, not only root score comparison;
- direct mate-distance unit tests at multiple distances;
- a forced perpetual cycle searched to the actual third occurrence from a
  compact position;
- fifty-move boundary tests at counters 99, 100, and checkmate on move 100;
- en-passant and castling fixtures;
- sanitizer runs.

## 7. Disabled optimization inventory

Classification meanings:

- **definitely reusable:** follows from generic game-tree mathematics or chess
  legality once value domains are correct;
- **probably reusable:** strong structural reason, but implementation-specific
  proof/tests are required;
- **uncertain:** normal Stockfish justification depends materially on
  conventional evaluation or empirical tuning;
- **fundamentally incompatible:** cannot represent the requested objective
  without changing its semantics.

| Optimization/component | Status | Why unsafe now | Property required before enabling |
|---|---|---|---|
| Full-width alpha-beta | **Definitely reusable; already used** | N/A after leaf fixes | Values form a deterministic zero-sum total order and child bounds use the same objective. |
| PVS/null-window root search | **Definitely reusable** | Non-best PV reconstruction/bounds need tests | Fail-soft/fail-hard bounds must preserve the same negamax order; compare against full-window oracle. |
| Iterative deepening | **Definitely reusable; already used** | Stop/ponder behavior incomplete | Last completed iteration is retained and incomplete bounds never select a move. |
| Legal move generation, make/undo | **Definitely reusable** | Objective-independent | State and accumulator restore exactly; special-move tests pass. |
| Basic deterministic move ordering | **Definitely reusable** | Ordering must not prune | Reordering alone returns identical score and optimal set. |
| TT move ordering only | **Definitely reusable** | Must not consume cached value | TT move is legal and used only as ordering hint. |
| Transposition values/bounds | **Probably reusable** | Objective domain and repetition history differ | Separate objective key/domain; exact bound semantics; rule-50/history-safe keying or conservative cutoff policy. |
| Aspiration windows | **Probably reusable** | Failure recovery assumes valid previous score | Re-search always expands to an exact containing window; oracle equivalence across failures. |
| Mate-distance pruning | **Probably reusable** | Existing helper names/sign meaning are normal-centric | Prove objective-aware upper/lower mate bounds and distance ordering. |
| Conventional capture/SEE ordering | **Probably reusable as ordering only** | Likely orders loss-relevant moves poorly | Must not prune; score invariance under ordering. |
| History/killer/countermove ordering | **Probably reusable as ordering only** | Learned “good move” direction comes from normal fail-highs | Train/update on loss-objective cutoffs and verify it changes order only. |
| Lazy SMP / helper threads | **Probably reusable** | Current helpers would run normal search; voting is normal-score-specific | Every worker uses same objective; arbitration compares exact loss scores and incomplete results safely. |
| Reversed Syzygy WDL | **Probably reusable** | Normal root ranks have opposite preference | Formal WDL mapping loss > draw > win; rule-50 consistency; oracle fixtures. |
| Reversed DTZ tie-breaking | **Uncertain** | DTZ is not identical to mate distance and interacts with zeroing/rule 50 | Prove shorter/longer DTZ ordering implements the chosen loss/draw/win policy. |
| Quiescence move continuation | **Uncertain** | Tactical stability remains useful | Define a loss-objective horizon and show qsearch terminal/leaf values converge appropriately. |
| Qsearch stand pat | **Uncertain** | Stand pat behaves like a pass and is fragile in zugzwang/check | Prove stand-pat is a valid bound for the chosen loss evaluator at every eligible node. |
| Late move reductions | **Uncertain** | Selective depth assumes normal ordering and empirical fail-high behavior | Reduced search plus re-search returns oracle-equivalent results on exhaustive shallow trees; retune for loss ordering. |
| Singular extensions / multi-cut | **Uncertain** | Depend on TT bounds, expected cut nodes, and normal tuned margins | Objective-domain TT correctness plus formal bound proof and exhaustive differential tests. |
| Check extensions | **Probably reusable** | Checks are tactically forcing under either objective, but sign preference reverses | Extension changes depth only and must preserve fixed-depth reference results under a defined selective-depth contract. |
| Razoring | **Uncertain** | Assumes conventional static eval predicts search fail-low | Establish loss-evaluator error bounds sufficient for the razor margin. |
| Reverse futility pruning | **Uncertain** | Same issue; margins are conventionally tuned | Prove a safe upper bound on all child loss values. |
| Parent futility pruning | **Uncertain** | Sacrifices and self-blocking moves may be precisely loss-optimal | Prove pruned moves cannot exceed alpha under loss utility. |
| SEE pruning | **Uncertain** | Losing material may be desirable, so normal exchange direction is not predictive | Derive loss-objective tactical bounds; normal SEE may remain ordering-only. |
| Null-move pruning | **Uncertain/high risk** | Passing is illegal and zugzwang is central to selfmate/loss play | Prove null fail-high is a valid lower bound for the position class; likely require many exclusions. |
| ProbCut | **Uncertain** | Statistical correlation is trained on normal search values | Re-establish correlation and false-cut rate for loss values, then differential-test. |
| Correction history | **Uncertain** | Learns normal static-to-search residuals | Train exclusively on objective-tagged loss values; never share normal history. |
| Normal WDL conversion | **Fundamentally incompatible as objective** | Models normal self-play outcomes, not reversed-game equilibrium | A separately trained/calibrated loss-game model is required. |
| `Skill Level` random suboptimal selection | **Fundamentally incompatible** | Intentionally perturbs the selected optimum | Must remain disabled in exact reference mode. |
| Root-only reverse normal search | **Fundamentally incompatible** | Future players optimize normal chess, not recursive loss | Cannot be repaired without changing the recursive backup policy. |
| Normal best-thread voting | **Fundamentally incompatible unchanged** | Special-cases normal wins/losses and score direction | Replace with objective-aware arbitration. |
| Expectimax human model in negamax driver | **Fundamentally incompatible with this driver** | Expectation is not alternating max with sign negation | Use a separate stochastic backup driver sharing position/evaluator infrastructure. |

## 8. Architecture review

### What is good

- Normal Stockfish `search()` is untouched.
- Loss search is single-threaded and excludes unproven pruning.
- Objective-specific terminal and leaf values have a named boundary.
- The fixed-color exhaustive oracle independently checks alternating max/min
  backup.
- Diagnostics now preserve pre-root history for exact-position checks and expose
  PVs.

### What should change before optimization

The current design couples three concepts that should be separate:

1. **Outcome semantics:** terminal ordering, draw value, mate distance.
2. **Leaf evaluator:** NNUE adapter, deterministic test evaluator, or future
   learned model.
3. **Backup operator/search driver:** zero-sum negamax, fixed-color minimax,
   expectimax, or risk-sensitive aggregation.

Recommended shape:

```text
SearchModel
  - terminal_value(position, context)
  - leaf_value(position, context)
  - value_perspective

BackupPolicy
  - node_role(position, root_context)
  - initialize()
  - combine(accumulator, child)
  - transform_child(child)
  - supports_alpha_beta

ReferenceSearch
  - legality, recursion, PV, depth, stop
  - no chess-objective assumptions
```

For the immediate zero-sum loss game, a compile-time `NegamaxModel` is simpler
and safer than a virtual call at every leaf. A future probabilistic human model
would use an `ExpectimaxBackup` rather than pretending to fit
`SearchObjectivePolicy`.

### Required correctness repair phase

Before optimization, perform a small **Milestone 2b**:

1. introduce a deterministic test leaf evaluator that is valid in every legal
   position, including check;
2. make NNUE loss evaluation explicit with zero optimism, never worker-stale
   optimism;
3. define horizon-in-check behavior (recommended: the reference evaluator must
   itself be valid in check; do not silently add variable-depth evasions);
4. give the oracle independent terminal constants and compare optimal move sets;
5. add direct mate-distance tests and debug/assertion builds;
6. complete ponder/infinite and objective-aware diagnostic score behavior;
7. rerun all randomized and hand-crafted fixtures.

Only after Milestone 2b passes should optimization work be considered.

## 9. Final recommendation

Do not add pruning, TT cutoffs, move ordering heuristics, threading, or Syzygy
yet.

The core recursive sign and max/min logic is correct, and the Pauly fixture
demonstrates genuine recursive selfmate behavior rather than root-only move
degradation. But shared invalid leaf evaluation prevents the current passing
oracle suite from being a complete correctness certificate.

Approve a narrow correctness-repair milestone first, followed by a second formal
audit of the repaired reference search.
