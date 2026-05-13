"""Helpers for inspecting items in a turn's stream.

The ``item/completed`` events carry a typed discriminated union: every
``Item`` has a ``type`` field, and the rest of its shape depends on the
type. The full set is documented in ``schemas/v2/Item*.json``; the
constants in :class:`codex_control.protocol.types.ItemType` cover the
ones we need to reason about.

These helpers are deliberately tiny and pure — they take an iterable of
items and return derived data. Higher-level code (verifiers, reward
functions) layers on top of these.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Iterator

from .protocol.types import Item, ItemType


def final_text(items: Iterable[Item]) -> str:
    """Concatenate every ``agentMessage`` ``text`` in order, newline-joined.

    This is the "final answer" string for a turn: most tasks have one
    agent message at the end, but some have several streamed pieces.
    """
    return "\n".join(
        it.get("text", "")
        for it in items
        if it.get("type") == ItemType.AGENT_MESSAGE and it.get("text")
    )


def last_agent_message(items: Iterable[Item]) -> str:
    """Return the last ``agentMessage.text`` in the stream, or ``""``."""
    last = ""
    for it in items:
        if it.get("type") == ItemType.AGENT_MESSAGE:
            text = it.get("text")
            if text:
                last = text
    return last


def items_of_type(items: Iterable[Item], type_name: str) -> Iterator[Item]:
    return (it for it in items if it.get("type") == type_name)


def command_executions(items: Iterable[Item]) -> Iterator[Item]:
    return items_of_type(items, ItemType.COMMAND_EXECUTION)


def file_changes(items: Iterable[Item]) -> Iterator[Item]:
    return items_of_type(items, ItemType.FILE_CHANGE)


def item_type_counts(items: Iterable[Item]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in items:
        t = it.get("type") or "?"
        counts[t] = counts.get(t, 0) + 1
    return counts


def command_string(item: Item) -> str:
    """Best-effort string form of a ``commandExecution`` item's command.

    The wire shape has drifted across Codex versions: ``command`` may be
    a list-of-args, a string, or live under ``commandActions``. We try
    the obvious places and join lists with spaces.
    """
    cmd: Any = item.get("command")
    if cmd is None:
        cmd = item.get("commandActions")
    if cmd is None:
        details = item.get("details")
        if isinstance(details, dict):
            cmd = details.get("command")
    if isinstance(cmd, list):
        return " ".join(str(c) for c in cmd)
    return str(cmd or "")


def summarise(item: Item) -> str:
    """Human-readable one-liner for tracing and debug output."""
    t = item.get("type", "?")
    if t == ItemType.USER_MESSAGE:
        content = item.get("content") or [{}]
        text = ""
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text", "")
        return f"userMessage      {text[:80]!r}"
    if t == ItemType.AGENT_MESSAGE:
        return f"agentMessage     {item.get('text', '')[:80]!r}"
    if t == ItemType.REASONING:
        return "reasoning        (hidden)"
    if t == ItemType.COMMAND_EXECUTION:
        cmd = command_string(item)
        exit_code = item.get("exitCode")
        if exit_code is None:
            details = item.get("details")
            if isinstance(details, dict):
                exit_code = details.get("exitCode")
        return f"commandExecution cmd={cmd[:80]!r} exit={exit_code}"
    if t == ItemType.FILE_CHANGE:
        path = item.get("path") or item.get("targetPath")
        if path is None:
            changes = item.get("changes")
            if isinstance(changes, list) and changes:
                first = changes[0]
                if isinstance(first, dict):
                    path = first.get("path")
        kind = item.get("kind")
        return f"fileChange       path={path} kind={kind}"
    if t == ItemType.MCP_TOOL_CALL:
        return f"mcpToolCall      tool={item.get('tool', '?')}"
    return f"{t:16} {json.dumps(item)[:80]}"
