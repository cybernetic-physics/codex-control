"""Verifier protocol and batteries.

In RL terminology, a *verifier* turns a finished rollout into a
real-valued reward (plus a structured "what happened" payload for
analysis). Different tasks call for different verifiers:

* :class:`RegexVerifier` — pattern-match the agent's final text. Cheap
  baseline; fits arithmetic, classification, "answer in one word".

* :class:`JsonSchemaVerifier` — parse the final message as JSON, hand it
  to a grader callable. Pairs perfectly with ``turn/start.outputSchema``.

* :class:`SubprocessVerifier` — run an external command, key on its exit
  code or stdout. The base for :class:`PytestVerifier`.

* :class:`PytestVerifier` — convenience subclass that runs pytest in the
  workspace and returns ``passed / total`` as a fractional reward.

* :class:`CompositeVerifier` — weighted sum of sub-verifiers. Useful
  when you want e.g. ``0.5 * tests_pass + 0.5 * style_score``.

Custom verifiers implement :class:`Verifier`. They take a :class:`Turn`
plus optional context (workspace path, expected answer, …) and return a
:class:`VerifierResult`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

from .items import last_agent_message
from .protocol.types import Turn

log = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class VerifierResult:
    """The output of one verification pass.

    ``reward`` is a float, typically in ``[0, 1]`` but the protocol
    doesn't enforce that — composite verifiers may exceed it. ``ok`` is
    a hard pass/fail (for "did the task succeed?"). ``info`` is a free-
    form bag of diagnostics for logs and trace files.
    """

    reward: float
    ok: bool
    reason: str = ""
    info: dict[str, Any] = dataclasses.field(default_factory=dict)


class Verifier(Protocol):
    """A turn-to-reward function."""

    def __call__(self, turn: Turn, /, **ctx: Any) -> VerifierResult: ...


# -----------------------------------------------------------------------
# Built-in verifiers
# -----------------------------------------------------------------------

class RegexVerifier:
    """Match a regex against the last agent message.

    The default reward shape is binary (1.0 on match, 0.0 otherwise);
    you can override ``reward_on_match`` for partial credit schemes.
    """

    def __init__(
        self,
        pattern: str | re.Pattern[str],
        *,
        reward_on_match: float = 1.0,
        reward_on_miss: float = 0.0,
    ) -> None:
        self._pattern = (
            pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)
        )
        self._on_match = reward_on_match
        self._on_miss = reward_on_miss

    def __call__(self, turn: Turn, /, **ctx: Any) -> VerifierResult:
        text = last_agent_message(turn.items)
        if self._pattern.search(text):
            return VerifierResult(
                reward=self._on_match,
                ok=True,
                reason=f"matched {self._pattern.pattern!r}",
                info={"final_text": text[:200]},
            )
        return VerifierResult(
            reward=self._on_miss,
            ok=False,
            reason=f"no match for {self._pattern.pattern!r}",
            info={"final_text": text[:200]},
        )


class JsonSchemaVerifier:
    """Parse the final message as JSON and hand it to a grader.

    The "schema" name is aspirational — we don't validate against a
    JSON Schema here; that's the server's job when ``outputSchema`` is
    set on ``turn/start``. This verifier just gives you a structured
    object to grade.
    """

    def __init__(
        self,
        grader: Callable[[dict[str, Any]], VerifierResult],
    ) -> None:
        self._grader = grader

    def _try_parse(self, text: str) -> Optional[dict[str, Any]]:
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None

    def __call__(self, turn: Turn, /, **ctx: Any) -> VerifierResult:
        text = last_agent_message(turn.items)
        parsed = self._try_parse(text)
        if parsed is None:
            return VerifierResult(
                reward=0.0,
                ok=False,
                reason="could not parse JSON",
                info={"final_text": text[:300]},
            )
        result = self._grader(parsed)
        if not result.info:
            result.info = {"parsed": parsed, "final_text": text[:300]}
        return result


class SubprocessVerifier:
    """Run an external command and grade on its exit code or output."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Optional[Path | str] = None,
        timeout: float = 60.0,
        grade: Optional[Callable[[subprocess.CompletedProcess[str]], VerifierResult]] = None,
    ) -> None:
        self._argv = list(argv)
        self._cwd = cwd
        self._timeout = timeout
        self._grade = grade or self._default_grade

    @staticmethod
    def _default_grade(
        cp: subprocess.CompletedProcess[str],
    ) -> VerifierResult:
        ok = cp.returncode == 0
        return VerifierResult(
            reward=1.0 if ok else 0.0,
            ok=ok,
            reason=f"exit={cp.returncode}",
            info={
                "stdout": cp.stdout[-1000:] if cp.stdout else "",
                "stderr": cp.stderr[-1000:] if cp.stderr else "",
                "exit_code": cp.returncode,
            },
        )

    def __call__(self, turn: Turn, /, **ctx: Any) -> VerifierResult:
        cwd = ctx.get("cwd", self._cwd)
        try:
            cp = subprocess.run(
                self._argv,
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return VerifierResult(
                reward=0.0,
                ok=False,
                reason=f"command timed out after {self._timeout}s",
                info={"argv": self._argv, "stdout": (exc.stdout or b"")[-500:] if isinstance(exc.stdout, bytes) else "",
                      "stderr": (exc.stderr or b"")[-500:] if isinstance(exc.stderr, bytes) else ""},
            )
        return self._grade(cp)


# -----------------------------------------------------------------------
# Pytest convenience
# -----------------------------------------------------------------------

_PYTEST_SUMMARY_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped)")


def _parse_pytest_summary(stdout: str) -> dict[str, int]:
    """Parse the trailing summary line of pytest -q (best effort)."""
    counts: dict[str, int] = {}
    for line in reversed(stdout.splitlines()):
        matches = _PYTEST_SUMMARY_RE.findall(line)
        if matches:
            for n, kind in matches:
                key = "errors" if kind in ("error", "errors") else kind
                counts[key] = int(n)
            break
    return counts


class PytestVerifier(SubprocessVerifier):
    """Run pytest in the rollout's workspace.

    Reward is ``passed / max(1, passed + failed + errors)`` — a partial-
    credit signal that's still 1.0 when all tests pass and 0.0 when none
    do. The verifier ignores skipped tests in the denominator.
    """

    def __init__(
        self,
        *,
        argv: Sequence[str] = ("python3", "-m", "pytest", "-q", "--tb=line", "--no-header"),
        cwd: Optional[Path | str] = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(argv, cwd=cwd, timeout=timeout, grade=self._grade_pytest)

    @staticmethod
    def _grade_pytest(
        cp: subprocess.CompletedProcess[str],
    ) -> VerifierResult:
        counts = _parse_pytest_summary(cp.stdout or "")
        passed = counts.get("passed", 0)
        failed = counts.get("failed", 0)
        errors = counts.get("errors", 0)
        total_run = passed + failed + errors
        denom = max(1, total_run)
        reward = passed / denom
        ok = failed == 0 and errors == 0 and passed > 0
        return VerifierResult(
            reward=reward,
            ok=ok,
            reason=f"pytest {passed}/{total_run} passed",
            info={
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "skipped": counts.get("skipped", 0),
                "total_run": total_run,
                "exit_code": cp.returncode,
                "stdout_tail": (cp.stdout or "")[-1000:],
            },
        )


# -----------------------------------------------------------------------
# Composite
# -----------------------------------------------------------------------

@dataclasses.dataclass
class _WeightedVerifier:
    verifier: Verifier
    weight: float = 1.0
    name: str = ""


class CompositeVerifier:
    """Weighted-sum reduction over multiple verifiers.

    ``ok`` aggregates with ``all(...)`` (every sub-verifier must pass for
    the composite to be considered ``ok``). ``reason`` summarises which
    parts passed. Sub-verifier infos are collected under ``parts``.
    """

    def __init__(self, parts: Sequence[tuple[Verifier, float, str]]):
        self._parts = [
            _WeightedVerifier(verifier=v, weight=w, name=n) for v, w, n in parts
        ]

    def __call__(self, turn: Turn, /, **ctx: Any) -> VerifierResult:
        total_weight = sum(p.weight for p in self._parts) or 1.0
        reward = 0.0
        infos: list[dict[str, Any]] = []
        ok = True
        reasons: list[str] = []
        for p in self._parts:
            sub = p.verifier(turn, **ctx)
            reward += (p.weight / total_weight) * sub.reward
            ok = ok and sub.ok
            reasons.append(f"{p.name}:{sub.reward:.2f}({sub.reason})")
            infos.append({"name": p.name, "weight": p.weight, **dataclasses.asdict(sub)})
        return VerifierResult(
            reward=reward,
            ok=ok,
            reason="; ".join(reasons),
            info={"parts": infos},
        )
