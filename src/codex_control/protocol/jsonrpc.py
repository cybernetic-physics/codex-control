"""JSON-RPC 2.0 framing helpers.

Tiny, deliberate, and free of I/O. Tests can use these without bringing
up a session.

We classify every incoming object into one of four kinds:

* ``request``    — peer asking us something (has ``id`` and ``method``)
* ``notification`` — peer telling us something (has ``method`` but no ``id``)
* ``response``  — peer answering a request we sent (has ``id`` but no ``method``)
* ``unknown``   — anything else (logged and dropped at a higher layer)
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

from ..errors import ProtocolError

JsonValue = Any
JsonObject = dict[str, Any]

FrameKind = Literal["request", "notification", "response", "unknown"]


@dataclasses.dataclass(frozen=True)
class JsonRpcFrame:
    """Result of parsing one inbound JSON-RPC envelope.

    Exactly one of ``method``/``error``/``result`` is meaningful depending
    on ``kind``. We keep everything available so the dispatcher in
    :mod:`codex_control.session` can do its own routing.
    """

    kind: FrameKind
    id: Any | None
    method: str | None
    params: JsonObject
    result: JsonValue | None
    error: JsonObject | None
    raw: JsonObject


def build_request(request_id: int | str, method: str, params: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def build_notification(method: str, params: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def build_response(request_id: int | str, result: JsonValue) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def build_error_response(request_id: int | str, code: int, message: str) -> JsonObject:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def parse_frame(obj: JsonObject) -> JsonRpcFrame:
    """Classify an inbound envelope.

    Raises :class:`ProtocolError` if the envelope is structurally bad.
    Non-object payloads are caller-rejected before we get here.
    """
    if not isinstance(obj, dict):
        raise ProtocolError(f"expected JSON object frame, got {type(obj).__name__}")

    mid = obj.get("id")
    method = obj.get("method")
    params = obj.get("params") or {}
    if not isinstance(params, dict):
        # Some servers send list-style params; coerce to {"_args": [...]} so
        # downstream code keeps a stable shape. This is defensive — we don't
        # produce such frames ourselves.
        params = {"_args": params}

    if method is not None and mid is not None:
        return JsonRpcFrame(
            kind="request",
            id=mid,
            method=method,
            params=params,
            result=None,
            error=None,
            raw=obj,
        )
    if method is not None:
        return JsonRpcFrame(
            kind="notification",
            id=None,
            method=method,
            params=params,
            result=None,
            error=None,
            raw=obj,
        )
    if mid is not None and ("result" in obj or "error" in obj):
        return JsonRpcFrame(
            kind="response",
            id=mid,
            method=None,
            params={},
            result=obj.get("result"),
            error=obj.get("error"),
            raw=obj,
        )
    return JsonRpcFrame(
        kind="unknown",
        id=mid,
        method=method,
        params=params,
        result=None,
        error=None,
        raw=obj,
    )
