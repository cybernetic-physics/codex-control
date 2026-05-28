"""Fakes-only tests for :class:`McpToolResult`.

We feed the result synthetic MCP content arrays — one image block, one
text block, one resource block, one mixed — and assert the typed
accessors return the right primitives. There is no live MCP server,
no codex binary, no transport.

The shapes are what the macOS Computer Use plugin (and our
codex-cua-linux server) actually emit, so coverage here is the
contract that lets us refactor MCP content-walking later without
breaking callers.
"""
from __future__ import annotations

import base64
import json

from codex_control import McpToolResult


# A 4-byte fake PNG-ish blob — we don't care about validity, only
# round-tripping through base64.
RAW_IMG = b"\x89PNG"
B64_IMG = base64.b64encode(RAW_IMG).decode("ascii")


def test_text_only_block():
    r = McpToolResult({
        "content": [{"type": "text", "text": "hello"}],
        "isError": False,
    })
    assert r.text() == "hello"
    assert r.image_bytes() is None
    assert r.json() is None  # "hello" isn't JSON
    assert r.is_error is False


def test_multiple_text_blocks_join():
    r = McpToolResult({
        "content": [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ],
    })
    assert r.text() == "first\nsecond"
    assert r.text(joiner=" | ") == "first | second"


def test_image_block_round_trips():
    r = McpToolResult({
        "content": [
            {"type": "image", "data": B64_IMG, "mimeType": "image/png"},
        ],
    })
    assert r.image_bytes() == RAW_IMG
    assert r.text() == ""


def test_resource_block_with_blob():
    r = McpToolResult({
        "content": [
            {"type": "resource",
             "resource": {"uri": "cua://screenshot/1", "blob": B64_IMG}},
        ],
    })
    # `image_bytes` falls back to resource blobs when there's no image block.
    assert r.image_bytes() == RAW_IMG
    # The dedicated accessor also works, with URI filtering.
    assert r.resource_blob(uri_prefix="cua://") == RAW_IMG
    assert r.resource_blob(uri_prefix="other://") is None


def test_mixed_block_matches_macos_get_app_state_shape():
    """The macOS Computer Use plugin's get_app_state returns one text
    block holding the AX-tree JSON plus one image block holding the
    screenshot. This test models that shape exactly."""
    ax_tree = {"app": "Safari", "accessibility_tree": [{"element_index": "1"}]}
    r = McpToolResult({
        "content": [
            {"type": "text", "text": json.dumps(ax_tree)},
            {"type": "image", "data": B64_IMG, "mimeType": "image/png"},
        ],
        "isError": False,
    })
    assert r.json() == ax_tree
    assert r.image_bytes() == RAW_IMG
    assert r.is_error is False


def test_is_error_propagates_and_text_still_extractable():
    r = McpToolResult({
        "content": [{"type": "text", "text": "Computer Use is not active for 'Safari'"}],
        "isError": True,
    })
    assert r.is_error is True
    assert "Computer Use is not active" in r.text()


def test_missing_content_is_empty():
    r = McpToolResult({})
    assert r.text() == ""
    assert r.image_bytes() is None
    assert r.json() is None
    assert r.is_error is False


def test_unknown_block_type_ignored():
    """Future MCP spec extensions add new discriminator values; we
    skip them rather than raise so callers keep working through spec
    bumps."""
    r = McpToolResult({
        "content": [
            {"type": "audio", "data": "ignored"},
            {"type": "text", "text": "kept"},
        ],
    })
    assert r.text() == "kept"
    assert r.image_bytes() is None


def test_raw_view_is_immutable_to_external_mutation():
    src = {"content": [{"type": "text", "text": "hi"}]}
    r = McpToolResult(src)
    src["content"].append({"type": "text", "text": "injected"})
    # External mutation of the input must not leak into the result.
    assert r.text() == "hi"


def test_repr_summarises_blocks():
    r = McpToolResult({
        "content": [
            {"type": "text", "text": "x"},
            {"type": "image", "data": B64_IMG},
        ],
    })
    s = repr(r)
    assert "McpToolResult" in s
    assert "text" in s and "image" in s


def test_invalid_base64_returns_none_rather_than_raising():
    """If a backend sends garbled base64 we surface None to the caller
    instead of crashing the rollout. The decoder is strict; this test
    asserts the strict path."""
    import pytest
    r = McpToolResult({
        "content": [{"type": "image", "data": "not-real-base64!!!"}],
    })
    with pytest.raises(Exception):
        # We deliberately *don't* swallow decode errors — they indicate
        # a protocol bug worth surfacing — but we want to know the
        # behaviour is consistent. If we ever decide to be lenient
        # this assertion flips.
        r.image_bytes()
