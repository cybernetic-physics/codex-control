# codex-control examples

Each script here corresponds to one experiment in
`experiments/app-server/` and reproduces it through the public
`codex_control` API only. They serve as both regression tests for the
library surface and copy-pasteable patterns for RL/auto-research code.

Run them from the repo root with `uv`:

```bash
cd src/codex-control
uv sync --extra websocket
uv run python examples/01_smoke.py
uv run python examples/02_synthetic_traces.py 4
uv run python examples/03_grpo_group_sample.py 4 20
# ...
uv run python examples/13_introspection.py
```

The remote examples need a `codex app-server --listen ws://...` running
somewhere reachable; pass `REMOTE_URL` and `WS_TOKEN` env vars.

Traces are written under `examples/traces/<NN>/` so they don't collide
with the original experiment outputs.
