"""Verifier unit tests (pure-Python; no Codex needed)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codex_control import (
    CompositeVerifier,
    JsonSchemaVerifier,
    PytestVerifier,
    RegexVerifier,
    Turn,
    VerifierResult,
)


def _turn_with(text: str) -> Turn:
    return Turn(
        thread_id="T",
        turn_id="U",
        status="completed",
        items=[{"type": "agentMessage", "text": text}],
    )


def test_regex_verifier_match() -> None:
    v = RegexVerifier(r"\b391\b")
    r = v(_turn_with("the answer is 391, definitely"))
    assert r.ok and r.reward == 1.0


def test_regex_verifier_miss() -> None:
    v = RegexVerifier(r"\b391\b")
    r = v(_turn_with("the answer is 42"))
    assert not r.ok and r.reward == 0.0


def test_json_schema_verifier_parses_fenced() -> None:
    def grader(obj: dict) -> VerifierResult:
        return VerifierResult(reward=float(obj["answer"] == 391), ok=obj["answer"] == 391)

    v = JsonSchemaVerifier(grader)
    r = v(_turn_with("Here you go:\n```json\n{\"answer\": 391}\n```"))
    assert r.ok and r.reward == 1.0
    assert r.info["parsed"]["answer"] == 391


def test_json_schema_verifier_unparseable() -> None:
    v = JsonSchemaVerifier(lambda o: VerifierResult(reward=1.0, ok=True))
    r = v(_turn_with("totally not json"))
    assert not r.ok


def test_composite_verifier_weighted_sum() -> None:
    a = RegexVerifier(r"alpha")
    b = RegexVerifier(r"beta")
    c = CompositeVerifier([(a, 1.0, "alpha"), (b, 1.0, "beta")])
    r_all = c(_turn_with("alpha and beta"))
    assert r_all.ok and r_all.reward == 1.0
    r_half = c(_turn_with("only alpha here"))
    assert not r_half.ok
    assert r_half.reward == 0.5


def test_pytest_verifier_parses_summary(tmp_path: Path) -> None:
    """Run a tiny pytest in a temp dir and verify summary parsing."""
    src = tmp_path / "test_inner.py"
    src.write_text("def test_ok(): assert 1 == 1\ndef test_bad(): assert 1 == 2\n")
    # Use -p no:cacheprovider + --rootdir to avoid touching the outer pytest's config.
    v = PytestVerifier(
        argv=(
            "python3", "-m", "pytest", "-q", "--tb=line", "--no-header",
            "-p", "no:cacheprovider", "--rootdir", str(tmp_path),
            "test_inner.py",
        ),
        cwd=tmp_path,
        timeout=30.0,
    )
    # Make a fake Turn (the verifier only uses items via ctx; signature accepts it).
    fake_turn = Turn(thread_id="T", turn_id="U", status="completed")
    result = v(fake_turn, cwd=tmp_path)
    assert result.info["passed"] == 1
    assert result.info["failed"] == 1
    # Reward is 1 / 2 = 0.5 by partial credit.
    assert result.reward == 0.5
    assert not result.ok
