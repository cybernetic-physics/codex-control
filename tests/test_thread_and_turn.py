"""Thread + turn flow tests driven by FakeTransport."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from codex_control import CodexSession
from codex_control.protocol.methods import M, Notif

from conftest import FakeTransport


def _hs(transport: FakeTransport, frame: dict) -> None:
    if frame.get("method") == M.INITIALIZE:
        transport.push_nowait({
            "jsonrpc": "2.0", "id": frame["id"],
            "result": {"codexHome": "/x", "platformOs": "linux"},
        })


@pytest.mark.asyncio
async def test_start_thread_and_run_turn(fake_transport_factory) -> None:
    async def handler(transport: FakeTransport, frame: dict) -> None:
        _hs(transport, frame)
        method = frame.get("method")
        mid = frame.get("id")
        if method == M.THREAD_START:
            transport.push_nowait({
                "jsonrpc": "2.0", "id": mid,
                "result": {"thread": {"id": "T1", "ephemeral": True}},
            })
        elif method == M.TURN_START:
            transport.push_nowait({
                "jsonrpc": "2.0", "id": mid,
                "result": {"turn": {"id": "U1"}},
            })
            # Fire item + completed events.
            transport.push_nowait({
                "jsonrpc": "2.0", "method": Notif.ITEM_COMPLETED,
                "params": {"threadId": "T1", "item": {"type": "agentMessage", "text": "pong"}},
            })
            transport.push_nowait({
                "jsonrpc": "2.0", "method": Notif.TURN_COMPLETED,
                "params": {"threadId": "T1", "turn": {"id": "U1", "status": "completed"}},
            })
        elif method == M.THREAD_ARCHIVE:
            transport.push_nowait({"jsonrpc": "2.0", "id": mid, "result": {}})

    t = fake_transport_factory(handler)
    async with CodexSession(t) as session:
        thread = await session.start_thread()
        assert thread.thread_id == "T1"
        turn = await thread.run_turn("hi", timeout=2.0)
        assert turn.status == "completed"
        assert turn.final_text == "pong"
        await thread.archive()


@pytest.mark.asyncio
async def test_turn_steer_uses_expected_turn_id(fake_transport_factory) -> None:
    captured: list[dict[str, Any]] = []

    async def handler(transport: FakeTransport, frame: dict) -> None:
        _hs(transport, frame)
        method = frame.get("method")
        mid = frame.get("id")
        if method == M.THREAD_START:
            transport.push_nowait({"jsonrpc": "2.0", "id": mid,
                                    "result": {"thread": {"id": "T1"}}})
        elif method == M.TURN_START:
            transport.push_nowait({"jsonrpc": "2.0", "id": mid,
                                    "result": {"turn": {"id": "U99"}}})
        elif method == M.TURN_STEER:
            captured.append(frame["params"])
            transport.push_nowait({"jsonrpc": "2.0", "id": mid, "result": {"turnId": "U99"}})
            transport.push_nowait({
                "jsonrpc": "2.0", "method": Notif.TURN_COMPLETED,
                "params": {"threadId": "T1", "turn": {"id": "U99", "status": "completed"}},
            })

    t = fake_transport_factory(handler)
    async with CodexSession(t) as session:
        thread = await session.start_thread()
        handle = await thread.start_turn("essay")
        await handle.steer("STOP")
        async with handle.subscription:
            from codex_control.turn import collect_turn
            await collect_turn(handle, timeout=2.0)
    assert captured
    assert captured[0]["expectedTurnId"] == "U99"
    assert captured[0]["input"][0]["text"] == "STOP"


@pytest.mark.asyncio
async def test_collect_turn_filters_by_thread(fake_transport_factory) -> None:
    """Notifications for sibling threads should not bleed in."""
    async def handler(transport: FakeTransport, frame: dict) -> None:
        _hs(transport, frame)
        method = frame.get("method")
        mid = frame.get("id")
        if method == M.THREAD_START:
            transport.push_nowait({"jsonrpc": "2.0", "id": mid,
                                    "result": {"thread": {"id": "T1"}}})
        elif method == M.TURN_START:
            transport.push_nowait({"jsonrpc": "2.0", "id": mid,
                                    "result": {"turn": {"id": "U1"}}})
            # A noise event from a sibling thread.
            transport.push_nowait({
                "jsonrpc": "2.0", "method": Notif.ITEM_COMPLETED,
                "params": {"threadId": "OTHER", "item": {"type": "agentMessage", "text": "noise"}},
            })
            transport.push_nowait({
                "jsonrpc": "2.0", "method": Notif.ITEM_COMPLETED,
                "params": {"threadId": "T1", "item": {"type": "agentMessage", "text": "real"}},
            })
            transport.push_nowait({
                "jsonrpc": "2.0", "method": Notif.TURN_COMPLETED,
                "params": {"threadId": "T1", "turn": {"id": "U1", "status": "completed"}},
            })

    t = fake_transport_factory(handler)
    async with CodexSession(t) as session:
        thread = await session.start_thread()
        turn = await thread.run_turn("ping", timeout=2.0)
    assert turn.final_text == "real"
    assert len(turn.items) == 1
