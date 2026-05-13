"""Approval-handler unit tests."""

from __future__ import annotations

from codex_control import AlwaysAccept, AlwaysDecline, Composed, RegexGate
from codex_control.protocol.methods import ServerReq


def test_always_decline() -> None:
    h = AlwaysDecline()
    assert h(ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL, {"command": "anything"}) == {
        "decision": "decline"
    }


def test_always_accept() -> None:
    h = AlwaysAccept()
    cmd = h(ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL, {"command": "ls"})
    assert cmd == {"decision": "acceptForSession"}
    patch = h(ServerReq.APPLY_PATCH_APPROVAL, {})
    assert patch == {"decision": "approved"}


def test_regex_gate_deny_wins() -> None:
    g = RegexGate(deny=[r"\brm\s+-rf\b"], allow=[r"^ls\b"], default="accept")
    assert g(ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL, {"command": "rm -rf /"}) == {
        "decision": "decline"
    }
    assert g(ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL, {"command": "ls -la"}) == {
        "decision": "acceptForSession"
    }
    assert g(ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL, {"command": "pwd"}) == {
        "decision": "accept"
    }


def test_regex_gate_accepts_list_commands() -> None:
    g = RegexGate(deny=[r"\brm -rf\b"])
    out = g(ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL, {"command": ["rm", "-rf", "/"]})
    assert out == {"decision": "decline"}


def test_regex_gate_file_change_default_accept() -> None:
    g = RegexGate()
    assert g(ServerReq.FILE_CHANGE_REQUEST_APPROVAL, {"path": "x.py"}) == {"decision": "accept"}


def test_composed_first_wins() -> None:
    strict = RegexGate(deny=[r"\brm"], default="accept")
    permissive = AlwaysAccept()
    c = Composed([strict, permissive])
    assert c(ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL, {"command": "rm /"}) == {
        "decision": "decline"
    }
