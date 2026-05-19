from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_core_import_surface_does_not_require_codex_env() -> None:
    """Core imports must work without verifier compatibility extras."""

    repo = Path(__file__).resolve().parents[1]
    code = (
        "import codex_control; "
        "print(codex_control.CodexSession.__name__); "
        "print(codex_control.StdioTransport.__name__)"
    )
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code],
        env={"PYTHONPATH": str(repo / "src")},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["CodexSession", "StdioTransport"]


def test_verifier_import_error_is_actionable_without_codex_env() -> None:
    repo = Path(__file__).resolve().parents[1]
    code = "from codex_control import JsonSchemaVerifier"
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code],
        env={"PYTHONPATH": str(repo / "src")},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert proc.returncode != 0
    assert "codex-control[verifiers-compat]" in proc.stderr
