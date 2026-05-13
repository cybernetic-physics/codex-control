"""End-to-end session tests against the FakeTransport."""

from __future__ import annotations

import asyncio

import pytest

from codex_control import CodexSession, RpcError
from codex_control.protocol.methods import M, Notif, ServerReq

from conftest import FakeTransport


def _handshake_reply(transport: FakeTransport, frame: dict) -> None:
    """Reply ``initialize`` requests with a minimal server-info payload."""
    if frame.get("method") == M.INITIALIZE:
        transport.push_nowait({
            "jsonrpc": "2.0",
            "id": frame["id"],
            "result": {"codexHome": "/codex", "platformOs": "linux"},
        })


async def _default_handler(transport: FakeTransport, frame: dict) -> None:
    _handshake_reply(transport, frame)


@pytest.mark.asyncio
async def test_session_handshake_records_server_info(fake_transport_factory) -> None:
    t = fake_transport_factory(_default_handler)
    async with CodexSession(t) as session:
        assert session.server_info["codexHome"] == "/codex"
    # ``initialized`` should have been notified after initialize.
    methods = [f.get("method") for f in t.sent]
    assert methods[:2] == [M.INITIALIZE, Notif.INITIALIZED]


@pytest.mark.asyncio
async def test_request_response_correlation(fake_transport_factory) -> None:
    async def handler(transport: FakeTransport, frame: dict) -> None:
        _handshake_reply(transport, frame)
        if frame.get("method") == "echo":
            transport.push_nowait({
                "jsonrpc": "2.0",
                "id": frame["id"],
                "result": {"echo": frame["params"]["msg"]},
            })

    t = fake_transport_factory(handler)
    async with CodexSession(t) as session:
        out = await session.request("echo", {"msg": "hi"})
        assert out == {"echo": "hi"}


@pytest.mark.asyncio
async def test_rpc_error_raised(fake_transport_factory) -> None:
    async def handler(transport: FakeTransport, frame: dict) -> None:
        _handshake_reply(transport, frame)
        if frame.get("method") == "boom":
            transport.push_nowait({
                "jsonrpc": "2.0",
                "id": frame["id"],
                "error": {"code": -32600, "message": "bad"},
            })

    t = fake_transport_factory(handler)
    async with CodexSession(t) as session:
        with pytest.raises(RpcError) as exc:
            await session.request("boom", {})
    assert exc.value.code == -32600


@pytest.mark.asyncio
async def test_notification_subscription(fake_transport_factory) -> None:
    async def handler(transport: FakeTransport, frame: dict) -> None:
        _handshake_reply(transport, frame)

    t = fake_transport_factory(handler)
    async with CodexSession(t) as session:
        sub = session.subscribe("evt")
        await t.push({"jsonrpc": "2.0", "method": "evt", "params": {"n": 1}})
        await t.push({"jsonrpc": "2.0", "method": "other", "params": {}})
        await t.push({"jsonrpc": "2.0", "method": "evt", "params": {"n": 2}})
        async with sub:
            first = await asyncio.wait_for(sub.get(), timeout=1)
            second = await asyncio.wait_for(sub.get(), timeout=1)
        assert first["params"]["n"] == 1
        assert second["params"]["n"] == 2


@pytest.mark.asyncio
async def test_approval_handler_invoked(fake_transport_factory) -> None:
    captured: list[dict] = []

    def gate(method: str, params: dict) -> dict:
        captured.append({"method": method, "params": params})
        return {"decision": "decline"}

    async def handler(transport: FakeTransport, frame: dict) -> None:
        _handshake_reply(transport, frame)

    t = fake_transport_factory(handler)
    async with CodexSession(t, approval_handler=gate) as session:
        await t.push({
            "jsonrpc": "2.0",
            "id": 42,
            "method": ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL,
            "params": {"command": "rm -rf /"},
        })
        # Wait for the session to write its reply.
        for _ in range(50):
            await asyncio.sleep(0.01)
            replies = [f for f in t.sent if f.get("id") == 42]
            if replies:
                break
        assert replies and replies[0]["result"] == {"decision": "decline"}
        assert captured and captured[0]["method"] == ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL


@pytest.mark.asyncio
async def test_wildcard_subscription_receives_all(fake_transport_factory) -> None:
    async def handler(transport: FakeTransport, frame: dict) -> None:
        _handshake_reply(transport, frame)

    t = fake_transport_factory(handler)
    async with CodexSession(t) as session:
        sub = session.subscribe()
        async with sub:
            await t.push({"jsonrpc": "2.0", "method": "a", "params": {}})
            await t.push({"jsonrpc": "2.0", "method": "b", "params": {}})
            first = await asyncio.wait_for(sub.get(), timeout=1)
            second = await asyncio.wait_for(sub.get(), timeout=1)
        methods = {first["method"], second["method"]}
        assert methods == {"a", "b"}
