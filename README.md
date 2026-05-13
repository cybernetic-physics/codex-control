# codex-control

Async Python library for puppeteering `codex app-server` — the JSON-RPC
interface OpenAI ships inside `codex-cli`. Builds first-class
`Thread`/`Turn`/`fork`/`steer`/`interrupt`/`rollback` verbs into a
small, typed, transport-agnostic surface, and layers RL primitives
(group sampling, GRPO advantage, fork-based tree search, budget-with-
steer multi-turn loops, RLVR verifiers) on top.

This package is the *online-RL puppet-strings layer* in the
`rl-agent-work` monorepo. The companion `codex-trainer` package
(forthcoming, also under `src/`) will use it to drive Codex against
custom trainable policies.

Pinned to the `codex-cli 0.128.0` v2 protocol surface
(`schemas/v2`); the protocol shape will drift across Codex releases —
regenerate `schemas/` and skim `protocol/methods.py` whenever you bump.

## Why

`codex exec` can't fork, can't steer mid-turn, and can't interrupt
without SIGKILL'ing the partial trace. `codex app-server` exposes
all three as first-class JSON-RPC verbs. This library is the
thin, typed Python adapter that lets RL training and auto-research
code use them.

## Install

```bash
uv add codex-control                  # local stdio path only
uv add 'codex-control[websocket]'     # remote ws:// transport too
uv add 'codex-control[test]'          # pytest extras
```

Inside this monorepo (editable install for development):

```bash
cd src/codex-control
uv sync --extra websocket --extra test
```

The Codex binary itself is **not** an installable Python dep; install it
separately (the experiments pin `codex-cli 0.128.0`).

## 30-second tour

```python
import asyncio
from codex_control import CodexSession

async def main():
    async with CodexSession.spawn() as session:
        thread = await session.start_thread()
        turn = await thread.run_turn("Reply with the word: pong")
        print(turn.final_text)
        await thread.archive()

asyncio.run(main())
```

Same code over a remote app-server:

```python
from codex_control import CodexSession

async with CodexSession.connect("ws://codex:8765", token="...") as session:
    ...
```

## What's in the box

| Module                       | Purpose                                                    |
| ---------------------------- | ---------------------------------------------------------- |
| `codex_control.protocol`     | Wire types (`Turn`, `TokenUsage`, …), method constants     |
| `codex_control.transport`    | `StdioTransport`, `WebSocketTransport` (lazy import)       |
| `codex_control.session`      | `CodexSession` — JSON-RPC dispatcher + notification fan-out |
| `codex_control.thread`       | `Thread` — high-level facade for one `thread/start`        |
| `codex_control.turn`         | `TurnHandle.steer/.interrupt`, `collect_turn`              |
| `codex_control.handlers`     | `RegexGate`, `AlwaysAccept`, `Composed`, …                 |
| `codex_control.items`        | helpers over the typed item discriminator                  |
| `codex_control.budget`       | `Budget`, `BudgetSteerWatcher`                             |
| `codex_control.rollouts`     | `parallel_rollouts`, `grpo_advantage`, `single_turn_group` |
| `codex_control.tree`         | fork-based tree search + UCB selector                      |
| `codex_control.verifiers`    | `Verifier` protocol + `Regex/JsonSchema/Pytest/Composite`  |
| `codex_control.rlvr`         | multi-turn RLVR loop with verifier + soft-limit steer      |
| `codex_control.introspect`   | capability dossier (`fetch_dossier`)                       |
| `codex_control.traces`       | JSONL/JSON trace writers                                   |

## Mapping to the original experiments

The `examples/` directory reproduces every experiment from
`experiments/app-server/` against the new public API:

| Experiment                       | Demonstrates                              | Library primitive used                          |
| -------------------------------- | ----------------------------------------- | ----------------------------------------------- |
| `01_smoke.py`                    | initialize / thread / turn happy path      | `CodexSession`, `Thread.run_turn`               |
| `02_synthetic_traces.py`         | K-parallel offline data                    | `parallel_rollouts`, `TraceWriter`              |
| `03_grpo_group_sample.py`        | GRPO group sampling + advantage            | `single_turn_group`, `grpo_advantage`           |
| `04_fork_tree_search.py`         | `thread/fork` branching                    | `Thread.fork`, `expand_all`, `select_uct`       |
| `05_turn_steer.py`               | mid-turn `turn/steer`                      | `TurnHandle.steer`                              |
| `06_tool_using_rollout.py`       | typed `commandExecution` / `fileChange`    | `items.summarise`, `item_type_counts`           |
| `07_approval_gate.py`            | programmatic command gate                  | `RegexGate`, `ApprovalHandler`                  |
| `08_rollback_resume.py`          | `thread/rollback` ablation                 | `Thread.rollback`                               |
| `09_rlvr_budget_eval.py`         | multi-turn RLVR with budget + steer       | `run_rlvr_episode`, `PytestVerifier`, `Budget`  |
| `10_prompt_control.py`           | base/developer-instructions matrix         | `start_thread(base_instructions=…)`             |
| `11_output_schema.py`            | JSON-schema-constrained finals             | `JsonSchemaVerifier`                            |
| `12_inject_items_curriculum.py`  | hint / few-shot injection                  | `build_developer_hint`, `build_demo_pair`       |
| `13_introspection.py`            | capability dossier                         | `fetch_dossier`                                 |
| `remote/14_remote_smoke.py`      | WS transport happy path                    | `CodexSession.connect`                          |
| `remote/15_remote_grpo.py`       | K parallel rollouts over one WS            | `parallel_rollouts` over `RemoteAppServer`      |

## Design notes

- **Transport-agnostic session.** `CodexSession` is built on a
  `Transport` ABC. Local Codex (stdio), remote Codex (websocket), and
  test fakes share the same dispatch loop. Reader/writer state lives in
  one place.

- **Subscribe-before-fire.** `Thread.start_turn` registers the
  subscription *before* sending `turn/start`, so no early `item/started`
  or `item/completed` notification is ever missed. Trace fidelity is
  not optional.

- **`Turn` is a value object.** `Thread.run_turn(...) → Turn` returns a
  typed dataclass with `.items`, `.status`, `.token_usage`,
  `.final_text`. The streaming object is `TurnHandle`; the finished
  object is `Turn`.

- **Approvals are pluggable.** `ApprovalHandler` is a `Protocol`. Ship
  with `AlwaysDecline` (safe default), `AlwaysAccept`, `RegexGate`,
  `Composed`. Custom handlers are 10 lines.

- **Verifiers are pluggable.** Same shape — `Verifier(Turn, **ctx) →
  VerifierResult`. Built-ins for regex/JSON/subprocess/pytest plus a
  weighted-sum `CompositeVerifier`.

- **Budget + steer are first-class.** `Budget` tracks turns and tokens;
  `BudgetSteerWatcher` fires `turn/steer` once when either crosses a
  soft threshold. Combined in `run_rlvr_episode`.

- **No magic strings.** Method names live in
  `codex_control.protocol.methods.M` / `Notif` / `ServerReq`. When the
  protocol drifts, you change one line.

- **Wire-traffic logging.** Every session can write a JSONL of every
  inbound/outbound frame (`log_rpc_path=`). Gold for debugging schema
  drift; grep for `"error"` first.

- **Escape hatch.** `CodexSession.request(method, params)` and
  `.subscribe(method)` are public. Anything the higher-level helpers
  don't yet wrap — `thread/compact/start`, `thread/goal/set`,
  `review/start`, future verbs — works straight through.

## Operational notes

- **Ephemeral vs persisted threads.** `ephemeral=True` keeps the thread
  in memory only — perfect for K-parallel group members. But
  `thread/fork` needs a *persisted* parent (`ephemeral=False`); the
  server returns `-32600 "no rollout found"` from an ephemeral source.
  Children of a persisted parent can themselves be ephemeral.

- **`thread/archive` on ephemeral** raises a JSON-RPC error. `Thread.archive`
  swallows it so cleanup paths are safe to call unconditionally.

- **`effort="minimal"` is incompatible with the default tool set.** Codex
  registers `image_gen` and `web_search` and the Responses API rejects
  those under minimal effort. Use `effort="low"` or strip the tools.

- **OpenAI structured outputs** (used by `turn/start.outputSchema`):
  every key in `properties` **must** appear in `required`, and
  `additionalProperties: false` is mandatory. Violating these returns
  `invalid_json_schema` and the turn ends `status="failed"`.

- **Token-usage notification** is `thread/tokenUsage/updated` (with the
  slash before `updated` — not `thread/tokenUsageUpdated`). Payload is
  `{total, last, modelContextWindow}` where `total` is cumulative.

## Testing

```bash
uv run --extra test pytest -q
```

The tests use a `FakeTransport` that scripts JSON-RPC responses; the
Codex binary is *not* required to run them.

## Status

- Pinned to `codex-cli 0.128.0`.
- Async-first; no sync surface.
- Python 3.10+.
- Apache-2.0.

The companion `codex-trainer` package (under
`src/codex-trainer/`, forthcoming) will depend on this one to drive RL
training against custom Responses-compatible policies.
