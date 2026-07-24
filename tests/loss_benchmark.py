#!/usr/bin/env python3
"""Permanent correctness/performance benchmark for intentional-loss search."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


RESULT_RE = re.compile(
    r"losscheck passed 1/1 depth (?P<depth>\d+) timing-runs (?P<timing_runs>\d+) "
    r"score (?P<score>-?\d+) "
    r"alpha-beta-nodes (?P<nodes>\d+) "
    r"oracle-nodes (?P<oracle_nodes>\d+) "
    r"elapsed-us (?P<elapsed_us>\d+) "
    r"nps (?P<nps>\d+) "
    r"cutoffs (?P<cutoffs>\d+) "
    r"tt-hits (?P<tt_hits>\d+) "
    r"expanded (?P<expanded>\d+) "
    r"legal-moves (?P<legal_moves>\d+) "
    r"branching-milli (?P<branching_milli>\d+) "
    r"optimal(?P<optimal>.*?) pv(?P<pv>.*)$"
)


@dataclass
class Result:
    id: str
    depth: int
    score: int
    nodes: int
    oracle_nodes: int
    elapsed_us: int
    nps: int
    cutoffs: int
    tt_hits: int
    expanded: int
    legal_moves: int
    branching_milli: int
    optimal: list[str]
    pv: list[str]
    verification_wall_ms: int


class Engine:
    def __init__(self, executable: Path) -> None:
        self.process = subprocess.Popen(
            [str(executable)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.send("uci")
        self.read_until(lambda line: line == "uciok")

    def send(self, command: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def read_until(self, predicate) -> str:
        assert self.process.stdout is not None
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("engine exited before producing a benchmark result")
            line = line.strip()
            if "CRITICAL ERROR" in line:
                raise RuntimeError(line)
            if predicate(line):
                return line

    def close(self) -> None:
        if self.process.poll() is None:
            self.send("quit")
        self.process.wait(timeout=10)


def percentage(current: float, reference: float, higher_is_better: bool) -> float:
    if reference == 0:
        return 0.0
    raw = 100.0 * (current - reference) / reference
    return raw if higher_is_better else -raw


def aggregate(results: list[Result]) -> dict[str, float]:
    nodes = sum(result.nodes for result in results)
    elapsed = sum(result.elapsed_us for result in results)
    expanded = sum(result.expanded for result in results)
    legal = sum(result.legal_moves for result in results)
    return {
        "nodes": nodes,
        "elapsed_us": elapsed,
        "nps": 1_000_000.0 * nodes / max(elapsed, 1),
        "cutoffs": sum(result.cutoffs for result in results),
        "tt_hits": sum(result.tt_hits for result in results),
        "tt_hit_rate": sum(result.tt_hits for result in results) / max(nodes, 1),
        "branching_factor": legal / max(expanded, 1),
        "verification_wall_ms": sum(result.verification_wall_ms for result in results),
    }


def parse_result(case_id: str, line: str, wall_ms: int) -> Result:
    match = RESULT_RE.search(line)
    if not match:
        raise RuntimeError(f"{case_id}: unrecognized result:\n{line}")
    values = match.groupdict()
    return Result(
        id=case_id,
        depth=int(values["depth"]),
        score=int(values["score"]),
        nodes=int(values["nodes"]),
        oracle_nodes=int(values["oracle_nodes"]),
        elapsed_us=int(values["elapsed_us"]),
        nps=int(values["nps"]),
        cutoffs=int(values["cutoffs"]),
        tt_hits=int(values["tt_hits"]),
        expanded=int(values["expanded"]),
        legal_moves=int(values["legal_moves"]),
        branching_milli=int(values["branching_milli"]),
        optimal=values["optimal"].split(),
        pv=values["pv"].split(),
        verification_wall_ms=wall_ms,
    )


def run_suite(
    executable: Path, cases: list[dict], samples: int, timing_runs: int
) -> list[Result]:
    engine = Engine(executable)
    results: list[Result] = []
    try:
        for case in cases:
            case_results: list[Result] = []
            for _ in range(samples):
                engine.send(case["command"])
                started = time.perf_counter()
                engine.send(f"losscheck {case['depth']} 1 1 {timing_runs}")
                line = engine.read_until(lambda value: "losscheck " in value)
                wall_ms = round(1000 * (time.perf_counter() - started))
                if "losscheck failed" in line:
                    raise AssertionError(f"{case['id']}: {line}")
                case_results.append(parse_result(case["id"], line, wall_ms))

            first = case_results[0]
            stable_fields = ("depth", "score", "oracle_nodes", "optimal", "pv")
            for sample in case_results[1:]:
                for field in stable_fields:
                    if getattr(sample, field) != getattr(first, field):
                        raise AssertionError(
                            f"{case['id']}: nondeterministic {field}: "
                            f"{getattr(first, field)} != {getattr(sample, field)}"
                        )

            for field in ("nodes", "cutoffs", "tt_hits", "expanded", "legal_moves",
                          "branching_milli", "elapsed_us"):
                setattr(
                    first,
                    field,
                    round(statistics.median(getattr(r, field) for r in case_results)),
                )
            first.nps = round(
                1_000_000 * first.nodes / max(first.elapsed_us, 1)
            )
            first.verification_wall_ms = round(
                statistics.median(r.verification_wall_ms for r in case_results)
            )
            results.append(first)
    finally:
        engine.close()
    return results


def git_revision(root: Path) -> str:
    process = subprocess.run(
        ["git", "-c", f"safe.directory={root.as_posix()}", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else "unknown"


def write_baseline(
    path: Path, root: Path, results: list[Result], samples: int, timing_runs: int
) -> None:
    payload = {
        "schema": 1,
        "revision": git_revision(root),
        "samples": samples,
        "timing_runs": timing_runs,
        "aggregate": aggregate(results),
        "positions": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote reference baseline: {path}")


def compare(results: list[Result], baseline: dict, samples: int) -> int:
    expected_by_id = {item["id"]: item for item in baseline["positions"]}
    failures: list[str] = []
    behavior_changes: list[str] = []

    for actual in results:
        expected = expected_by_id.get(actual.id)
        if expected is None:
            failures.append(f"{actual.id}: missing from reference baseline")
            continue

        if actual.score != expected["score"]:
            failures.append(
                f"{actual.id}: value expected {expected['score']}, got {actual.score}"
            )
        if actual.optimal != expected["optimal"]:
            failures.append(
                f"{actual.id}: optimal moves expected {expected['optimal']}, "
                f"got {actual.optimal}"
            )
        if actual.depth != expected["depth"]:
            failures.append(
                f"{actual.id}: depth expected {expected['depth']}, got {actual.depth}"
            )
        if actual.pv != expected["pv"]:
            behavior_changes.append(
                f"{actual.id}: PV expected {' '.join(expected['pv'])}, "
                f"got {' '.join(actual.pv)}"
            )

    actual_ids = {result.id for result in results}
    for missing in sorted(set(expected_by_id) - actual_ids):
        failures.append(f"{missing}: reference position was not run")

    current = aggregate(results)
    reference = baseline["aggregate"]

    print(f"Reference: {'PASS' if not failures else 'FAIL'}")
    print(f"Timing samples: {samples} (per-position median)")
    print(
        "Performance: "
        f"nodes {int(current['nodes'])} "
        f"({percentage(current['nodes'], reference['nodes'], False):+.1f}%), "
        f"NPS {current['nps']:.0f} "
        f"({percentage(current['nps'], reference['nps'], True):+.1f}%), "
        f"search wall {current['elapsed_us'] / 1000:.3f} ms "
        f"({percentage(current['elapsed_us'], reference['elapsed_us'], False):+.1f}%)"
    )
    print(
        "Behavior: "
        f"{'identical' if not behavior_changes else f'{len(behavior_changes)} PV change(s)'}; "
        f"cutoffs {int(current['cutoffs'])}; "
        f"TT hit rate {100 * current['tt_hit_rate']:.2f}%; "
        f"branching factor {current['branching_factor']:.2f}"
    )
    print(
        f"Verification wall: {int(current['verification_wall_ms'])} ms "
        "(includes exhaustive oracle and optimal-set enumeration)"
    )

    if failures:
        print("\nCorrectness regressions:")
        for failure in failures:
            print(f"  - {failure}")
    if behavior_changes:
        print("\nBehavior changes:")
        for change in behavior_changes:
            print(f"  - {change}")

    print("\nPer-position:")
    for result in results:
        print(
            f"  {result.id:24} d{result.depth:<2} "
            f"value {result.score:>6} nodes {result.nodes:>8} "
            f"cutoffs {result.cutoffs:>6} bf {result.branching_milli / 1000:>5.2f} "
            f"pv {' '.join(result.pv)}"
        )

    return 1 if failures else 0


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", nargs="?", default=str(root / "src" / "stockfish"))
    parser.add_argument(
        "--positions",
        type=Path,
        default=root / "tests" / "loss_benchmark_positions.json",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=root / "tests" / "loss_benchmark_baseline.json",
    )
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="timing samples per position; correctness must be deterministic across all samples",
    )
    parser.add_argument(
        "--timing-runs",
        type=int,
        default=100,
        help="reference alpha-beta repetitions per timing sample (the oracle runs once)",
    )
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.timing_runs < 1:
        parser.error("--timing-runs must be at least 1")

    cases = json.loads(args.positions.read_text(encoding="utf-8"))
    results = run_suite(
        Path(args.engine).resolve(), cases, args.samples, args.timing_runs
    )

    if args.write_baseline:
        write_baseline(
            args.baseline, root, results, args.samples, args.timing_runs
        )
        return 0

    if not args.baseline.exists():
        print(
            f"Missing baseline {args.baseline}; run with --write-baseline first",
            file=sys.stderr,
        )
        return 2

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    return compare(results, baseline, args.samples)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Benchmark failed: {error}", file=sys.stderr)
        raise SystemExit(1)
