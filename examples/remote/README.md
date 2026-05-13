# Remote control: Python client + `codex app-server` across containers

Ports `experiments/app-server/remote/` to the `codex-control` library.
The Python side is now whatever you can express with `codex_control`;
the server side is unchanged (`codex app-server --listen ws://...`).

```
                bridge net "codex-net"
            ┌──────────────────────────┐
codex-client│  ws://codex-server:8765  │codex-server
(python +   ├──────────────────────────┤(codex app-server
 codex-     │  Bearer <capability-tok> │ + --ws-auth
 control)   └──────────────────────────┘ capability-token)
```

Both containers share a private Docker bridge network; the server's
8765 is **not** published on the host.

## Files

| File                  | Purpose                                                                |
| --------------------- | ---------------------------------------------------------------------- |
| `14_remote_smoke.py`  | One-shot rollout: ``Reply: pong``. Drives `CodexSession.connect(...)`. |
| `15_remote_grpo.py`   | K-parallel rollouts on one WS via `parallel_rollouts`.                 |
| `Dockerfile.server`   | `node:20-slim` + `@openai/codex` + the entrypoint                      |
| `Dockerfile.client`   | `python:3.12-slim` + a wheel of `codex-control[websocket]`             |
| `entrypoint.sh`       | Copies host `auth.json` into container `CODEX_HOME`, exec codex        |
| `run.sh`              | Raw `docker run` orchestrator. Works on `docker compose v1` hosts too. |
| `compose.yaml`        | `docker compose v2` equivalent of `run.sh`                             |

The original demo copied a single `app_server_client.py` into the
client image. The codex-control port builds a wheel of the local
package (`uv build`) and installs that — so the image always tracks the
source you're working from.

## Run

From this directory:

```bash
bash run.sh smoke    # one-shot rollout; ~10s
bash run.sh grpo     # K=4 parallel rollouts on one WS; ~10s
K=8 bash run.sh grpo # bump parallelism
```

What `run.sh` does:

1. `openssl rand -hex 32` for the capability token, sha256 hash it.
2. `uv build` (or `python -m build`) to produce
   `_build/codex_control-0.1.0-py3-none-any.whl`.
3. `docker build` both images.
4. `docker network create codex-net`.
5. `docker run -d codex-server` with the host's `~/.codex/auth.json`
   mounted **read-only** into a side dir; the entrypoint copies it
   into the container's writable `$CODEX_HOME`.
6. `docker exec curl /readyz` until the WS listener is up.
7. `docker run --rm codex-client` with `REMOTE_URL` and `WS_TOKEN`
   inherited, runs the chosen demo.
8. On exit, the trap removes both containers and the network.

Override the codex version with `--build-arg CODEX_VERSION=...` if you
need to match a different schema set; the default tracks the version
the local `experiments/app-server/schemas/` were generated against.

## Compose v2 path

If you're on docker compose v2 you can skip `run.sh`:

```bash
# 1. Build the wheel that Dockerfile.client installs.
(cd ../.. && uv run --with build python -m build --wheel --outdir examples/remote/_build)

# 2. Set the auth env.
export WS_TOKEN=$(openssl rand -hex 32)
export WS_TOKEN_SHA256=$(printf '%s' "$WS_TOKEN" | openssl dgst -sha256 -hex | awk '{print $2}')
export CODEX_HOME_HOST="$HOME/.codex"

# 3. Up.
docker compose up --build
```

The default `CMD` runs the smoke; for grpo:

```bash
docker compose run --rm codex-client python3 /app/15_remote_grpo.py
```

`compose v1 + Docker 29` hits `KeyError: 'ContainerConfig'` on
recreate — use `run.sh` on those hosts.

## Why this matters for RL

- **Locality split.** Trainer in one container, Codex pool in another.
  Trainer process talks to N WS servers, K parallel threads per server.
  Add capacity by starting more server containers; no code change.
- **Sandboxing.** The Codex container can run with restricted caps, a
  read-only mount of `auth.json`, and a network policy that allows only
  the OpenAI Responses endpoint outbound (or a trainable-policy proxy).
- **Same verbs.** `turn/steer`, `turn/interrupt`, `thread/fork`,
  `thread/inject_items`, `outputSchema`, `approval_handler`,
  `thread/tokenUsage/updated` — every primitive demoed in the local
  examples works over WS by swapping `CodexSession.spawn(...)` for
  `CodexSession.connect(url, token=...)`. Nothing else changes.

## Auth model

`--ws-auth capability-token`. Two ways to configure on the server:

- `--ws-token-file /abs/path` — server reads raw token from disk.
- `--ws-token-sha256 HEX`     — server stores only the hash. **We use
  this.** The raw secret never appears in `ps` / `docker inspect` on
  the server container; the client holds it in its env and sends it as
  `Authorization: Bearer`.

For multi-tenant / cross-host: swap to `--ws-auth signed-bearer-token
--ws-shared-secret-file /abs/path` and JWTs (`--ws-issuer`,
`--ws-audience`, `--ws-max-clock-skew-seconds`).

## Gotchas captured the hard way

- **Don't bind-mount `~/.codex` read-only.** Codex needs to write its
  sqlite state DB; RO mount produces `(code: 8) attempt to write a
  readonly database` and the server limps along with degraded
  features. The pattern here — RO-mount `auth.json` into a side dir,
  copy it into a fully-writable `CODEX_HOME` at entrypoint — sidesteps
  that.
- **`node:20-slim` ships neither `wget` nor `curl`.** We install `curl`
  explicitly so `docker exec curl /readyz` and the compose
  `healthcheck` both work.
- **Origin header rejected.** `codex app-server` returns `403 Forbidden`
  to any handshake carrying an `Origin` header. The Python
  `websockets` library doesn't emit one for non-browser URIs; if you
  swap clients, strip `Origin` explicitly.
- **`docker compose v1 + Docker 29` is broken.** Recreate hits
  `KeyError: 'ContainerConfig'`. Use `run.sh`.
- **`auth.json` holds per-user OAuth tokens** that expire on a refresh
  schedule. If the demo silently stops working a week later, refresh
  on the host (`codex login`) and the next container start picks up the
  new tokens.

## What changed vs. `experiments/app-server/remote/`

- Client side uses `from codex_control import CodexSession,
  parallel_rollouts` instead of a vendored `app_server_client.py`.
- `Dockerfile.client` installs a wheel of `codex-control[websocket]`
  built by `run.sh`/compose instructions, rather than copying a single
  Python file.
- Image tags rebrand to `codex-control-server` / `codex-control-client`.
- Demo behaviour is byte-for-byte equivalent; the wire is the same.
