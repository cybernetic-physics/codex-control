"""Tests for the pure protocol layer."""

from __future__ import annotations

from codex_control.protocol.jsonrpc import (
    build_error_response,
    build_notification,
    build_request,
    build_response,
    parse_frame,
)
from codex_control.protocol.methods import M, Notif, ServerReq


def test_method_constants_are_str() -> None:
    assert isinstance(M.THREAD_START, str)
    assert M.TURN_STEER == "turn/steer"
    assert Notif.TURN_COMPLETED == "turn/completed"
    assert Notif.THREAD_TOKEN_USAGE_UPDATED == "thread/tokenUsage/updated"
    assert ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL == "item/commandExecution/requestApproval"


def test_build_request() -> None:
    f = build_request(1, "x/y", {"a": 1})
    assert f == {"jsonrpc": "2.0", "id": 1, "method": "x/y", "params": {"a": 1}}


def test_build_notification() -> None:
    f = build_notification("x/y", {"a": 1})
    assert "id" not in f
    assert f["method"] == "x/y"


def test_build_response_and_error() -> None:
    assert build_response(5, {"k": "v"})["result"] == {"k": "v"}
    err = build_error_response(5, -1, "boom")["error"]
    assert err == {"code": -1, "message": "boom"}


def test_parse_request_frame() -> None:
    f = parse_frame({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"x": 2}})
    assert f.kind == "request"
    assert f.method == "ping"
    assert f.params == {"x": 2}
    assert f.id == 1


def test_parse_notification_frame() -> None:
    f = parse_frame({"jsonrpc": "2.0", "method": "evt", "params": {"x": 1}})
    assert f.kind == "notification"
    assert f.method == "evt"
    assert f.id is None


def test_parse_response_frame_ok() -> None:
    f = parse_frame({"jsonrpc": "2.0", "id": 7, "result": {"ok": True}})
    assert f.kind == "response"
    assert f.result == {"ok": True}
    assert f.error is None


def test_parse_response_frame_err() -> None:
    f = parse_frame({"jsonrpc": "2.0", "id": 7, "error": {"code": -32600, "message": "no"}})
    assert f.kind == "response"
    assert f.error == {"code": -32600, "message": "no"}


def test_parse_unknown_frame() -> None:
    f = parse_frame({"jsonrpc": "2.0"})
    assert f.kind == "unknown"


def test_parse_coerces_list_params() -> None:
    f = parse_frame({"jsonrpc": "2.0", "method": "evt", "params": [1, 2, 3]})
    assert f.kind == "notification"
    assert f.params == {"_args": [1, 2, 3]}
