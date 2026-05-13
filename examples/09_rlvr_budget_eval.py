"""Multi-turn RLVR loop with budget + soft-limit steer + pytest verifier.

Uses :func:`codex_control.run_rlvr_episode`, :class:`PytestVerifier`,
and the canonical :func:`pytest_followup` retry builder.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from codex_control import (
    Budget,
    CodexSession,
    PytestVerifier,
    TraceWriter,
    pytest_followup,
    run_rlvr_episode,
)


MATH_UTILS = '''\
def divide(a, b):
    # BUG: should be a / b
    return a + b


def multiply(a, b):
    # BUG: should be a * b
    return a - b


def power(base, exp):
    # BUG: returns base * exp, should return base ** exp
    return base * exp


def factorial(n):
    # BUG: returns 0 for n == 0 (should be 1) and is off-by-one for n > 0
    if n <= 0:
        return 0
    return n * factorial(n - 2)
'''

TEST_MATH = '''\
from math_utils import divide, multiply, power, factorial


def test_divide():
    assert divide(10, 2) == 5.0
    assert divide(9, 3) == 3.0


def test_multiply():
    assert multiply(2, 3) == 6
    assert multiply(4, 5) == 20


def test_power():
    assert power(2, 10) == 1024
    assert power(3, 4) == 81


def test_factorial():
    assert factorial(0) == 1
    assert factorial(5) == 120
    assert factorial(6) == 720
'''


def setup_workspace(root: Path) -> None:
    (root / "math_utils.py").write_text(MATH_UTILS)
    (root / "test_math.py").write_text(TEST_MATH)
    (root / "conftest.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
    )


INITIAL_PROMPT = (
    "The package in this directory has bugs in `math_utils.py` that "
    "cause the tests in `test_math.py` to fail. Fix the code, run "
    "`python3 -m pytest -q` to confirm all tests pass, and reply with "
    "exactly 'DONE' on a line by itself when finished."
)


async def main() -> None:
    max_turns = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    max_tokens = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    traces = TraceWriter(Path(__file__).parent / "traces" / "09_rlvr")

    with tempfile.TemporaryDirectory(prefix="rlvr-") as workdir:
        wd = Path(workdir)
        setup_workspace(wd)

        async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
            thread = await session.start_thread(
                cwd=workdir, ephemeral=False,
                sandbox="workspace-write", approval_policy="never",
            )
            budget = Budget(max_turns=max_turns, max_tokens=max_tokens)
            verifier = PytestVerifier(cwd=wd, timeout=30.0)
            episode = await run_rlvr_episode(
                thread, INITIAL_PROMPT,
                verifier=verifier,
                budget=budget,
                followup_builder=pytest_followup,
                cwd=workdir,
                approval_policy="never",
                effort="low",
                per_turn_timeout=240.0,
                context={"cwd": wd},
            )
            await thread.archive()

    print(f"\n[RLVR] reward={episode.reward:.3f} breakdown={episode.reward_breakdown}")
    out = traces.write_episode(episode)
    print(f"[save] {out}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
