#!/usr/bin/env python3
"""Milestone-2 correctness checks for the reference intentional-loss search."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


SPARSE_FENS = (
    # Kings only: small randomized legal walks and draw-valued leaves.
    "8/8/8/3k4/8/4K3/8/8 w - - 0 1",
    # A few pieces create captures, checks, and asymmetric leaf evaluations.
    "8/8/3k4/8/3P4/4K3/8/8 w - - 0 1",
    "8/8/3k4/8/2n5/5K2/4R3/8 w - - 0 1",
    "8/5k2/8/3p4/4P3/8/5K2/8 w - - 0 1",
)

CHECKMATED_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
STALEMATED_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
PAULY_SELFMATE_FEN = "KB3N2/P1P1p1P1/5P1k/4P2p/7P/8/6B1/7b w - - 0 1"
MATE_OR_STALEMATE_FEN = "7k/8/4Q1K1/8/8/8/8/8 w - - 0 1"
ONLY_MOVE_FEN = "7k/8/6K1/8/8/8/8/7R b - - 0 1"

ORACLE_FIXTURES = (
    ("in-check-depth-zero-leaf", ONLY_MOVE_FEN, 0),
    ("zugzwang", "8/8/8/3k4/3P4/3K4/8/8 b - - 0 1", 4),
    ("underpromotion-selfmate", PAULY_SELFMATE_FEN, 4),
    ("mate-or-stalemate", MATE_OR_STALEMATE_FEN, 2),
    ("only-one-legal-move", ONLY_MOVE_FEN, 4),
    ("promotion-choices", "7k/P7/6K1/8/8/8/8/8 w - - 0 1", 3),
    (
        "perpetual-check-position",
        "5rk1/5p1p/3Nn1p1/3pP1P1/3q4/3R1Q2/PP6/1K6 b - - 1 40",
        3,
    ),
)


def run_engine(executable: str, commands: list[str]) -> str:
    process = subprocess.run(
        [executable],
        input="\n".join(commands + ["quit"]) + "\n",
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    output = process.stdout + process.stderr
    if process.returncode:
        raise RuntimeError(f"engine exited with {process.returncode}\n{output}")
    return output


def analyze(executable: str, commands: list[str], depth: int = 3) -> tuple[int, list[str]]:
    output = run_engine(
        executable,
        ["uci", *commands, f"losscheck {depth} 1 1"],
    )
    match = re.search(
        r"losscheck passed 1/1 depth \d+ score (-?\d+).*? pv(.*)", output
    )
    if not match:
        raise AssertionError(f"losscheck did not pass\n{output}")
    return int(match.group(1)), match.group(2).split()


def score_for(executable: str, fen: str, depth: int = 3) -> int:
    return analyze(executable, [f"position fen {fen}"], depth)[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", nargs="?", default="./stockfish")
    args = parser.parse_args()

    commands = ["uci"]
    for index, fen in enumerate(SPARSE_FENS):
        commands.extend(
            [f"position fen {fen}", f"losscheck 3 24 {0xC0FFEE + index}"]
        )

    output = run_engine(args.engine, commands)
    passed = re.findall(r"losscheck passed 24/24 depth 3", output)
    if len(passed) != len(SPARSE_FENS):
        raise AssertionError(f"randomized oracle comparison failed\n{output}")

    for name, fen, depth in ORACLE_FIXTURES:
        try:
            analyze(args.engine, [f"position fen {fen}"], depth)
        except AssertionError as error:
            raise AssertionError(f"{name}: {error}") from error

    checkmate = score_for(args.engine, CHECKMATED_FEN)
    stalemate = score_for(args.engine, STALEMATED_FEN)

    if checkmate != 32_000:
        raise AssertionError(
            f"root checkmate must have loss value 32000, got {checkmate}"
        )
    if stalemate != 0:
        raise AssertionError(f"stalemate must use draw utility 0, got {stalemate}")

    pauly_score, pauly_pv = analyze(
        args.engine, [f"position fen {PAULY_SELFMATE_FEN}"], 4
    )
    if pauly_score != 31_996 or pauly_pv != ["c7c8n", "e7e6", "g7g8b", "h1g2"]:
        raise AssertionError(
            f"Pauly selfmate expected forced underpromotion PV, got "
            f"{pauly_score} {pauly_pv}"
        )

    draw_score, draw_pv = analyze(
        args.engine, [f"position fen {MATE_OR_STALEMATE_FEN}"], 1
    )
    if draw_score != 0 or not draw_pv:
        raise AssertionError(
            f"mate-or-stalemate fixture must choose a draw, got {draw_score} {draw_pv}"
        )

    _, only_move_pv = analyze(args.engine, [f"position fen {ONLY_MOVE_FEN}"], 3)
    if not only_move_pv or only_move_pv[0] != "h8g8":
        raise AssertionError(f"only-move fixture chose {only_move_pv}")

    # The final ...Nf6-g8 recreates the initial position for the third time.
    # Unlike FEN-only checks, Engine retains the pre-root state chain here.
    analyze(
        args.engine,
        [
            "position startpos moves "
            "g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1"
        ],
        2,
    )

    print(
        "loss-search tests passed: "
        f"{len(SPARSE_FENS) * 24} randomized positions, "
        f"{len(ORACLE_FIXTURES)} motif fixtures, "
        "scores and optimal move sets match exhaustive oracle, "
        "recursive/terminal semantics verified"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
