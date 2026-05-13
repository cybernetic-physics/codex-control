"""Item helper unit tests."""

from __future__ import annotations

from codex_control import (
    command_executions,
    command_string,
    file_changes,
    final_text,
    item_type_counts,
    last_agent_message,
    summarise,
)


ITEMS = [
    {"type": "userMessage", "content": [{"type": "input_text", "text": "hi"}]},
    {"type": "reasoning"},
    {"type": "agentMessage", "text": "first"},
    {"type": "commandExecution", "command": ["ls", "-la"], "exitCode": 0},
    {"type": "fileChange", "path": "x.py", "kind": {"type": "add"}},
    {"type": "agentMessage", "text": "second"},
]


def test_final_text_concatenates_agent_messages() -> None:
    assert final_text(ITEMS) == "first\nsecond"


def test_last_agent_message() -> None:
    assert last_agent_message(ITEMS) == "second"


def test_command_executions_filter() -> None:
    cmds = list(command_executions(ITEMS))
    assert len(cmds) == 1
    assert command_string(cmds[0]) == "ls -la"


def test_file_changes_filter() -> None:
    fc = list(file_changes(ITEMS))
    assert len(fc) == 1
    assert fc[0]["path"] == "x.py"


def test_item_type_counts() -> None:
    counts = item_type_counts(ITEMS)
    assert counts == {
        "userMessage": 1,
        "reasoning": 1,
        "agentMessage": 2,
        "commandExecution": 1,
        "fileChange": 1,
    }


def test_summarise_smoke() -> None:
    for it in ITEMS:
        s = summarise(it)
        assert isinstance(s, str) and len(s) > 0
