"""Deprecated. Verifiers moved to :mod:`codex_env` in the five-package refactor.

This shim re-exports the canonical implementations from
:mod:`codex_env.verifiers` (and the protocol types from
:mod:`codex_env.protocols`) for one release of grace. Import directly
from ``codex_env`` going forward; this module will be removed in v0.2.

The deprecation is silent at import time because legitimate callers
(:mod:`codex_control.__init__`) re-export through here; a verbose warning
would fire spuriously on every ``import codex_control``. Use the
``codex_env`` import sites and drop ``codex_control.verifiers`` from your
imports to silence this category entirely.
"""

from __future__ import annotations

from codex_env.protocols import Verifier, VerifierResult
from codex_env.verifiers.builtins import (
    CompositeVerifier,
    JsonSchemaVerifier,
    PytestVerifier,
    RegexVerifier,
    SubprocessVerifier,
)

__all__ = [
    "CompositeVerifier",
    "JsonSchemaVerifier",
    "PytestVerifier",
    "RegexVerifier",
    "SubprocessVerifier",
    "Verifier",
    "VerifierResult",
]
