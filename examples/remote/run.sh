#!/usr/bin/env bash
# Orchestrate the two-container remote-control demo without docker-compose,
# which doesn't play nicely on every host (compose v1 + Docker 29).
#
# Layout:
#   docker network: codex-net (bridge)
#   container 1:    codex-server  (codex app-server, --listen ws://0.0.0.0:8765)
#   container 2:    codex-client  (Python client, REMOTE_URL → codex-server)
#
# Auth: 32-byte capability token from openssl rand -hex 32.
# Server gets only its sha256; client gets the raw token to send as
# Authorization: Bearer.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PKG_ROOT="$(cd "$HERE/../.." && pwd)"     # …/codex-control
cd "$HERE"

DEMO="${1:-smoke}"
NET="codex-net"
SERVER="codex-server"
CLIENT="codex-client"

CODEX_HOME_HOST="${CODEX_HOME_HOST:-$HOME/.codex}"
if [ ! -f "$CODEX_HOME_HOST/auth.json" ]; then
    echo "FAIL: $CODEX_HOME_HOST/auth.json does not exist." >&2
    echo "      Run 'codex login' on the host first." >&2
    exit 1
fi

# 1. Generate (or accept caller-supplied) capability token.
: "${WS_TOKEN:=$(openssl rand -hex 32)}"
WS_TOKEN_SHA256="$(printf '%s' "$WS_TOKEN" | openssl dgst -sha256 -hex | awk '{print $2}')"
echo "[run.sh] capability-token sha256 = ${WS_TOKEN_SHA256:0:16}…"

# 2. Build the codex-control wheel into ./_build so Dockerfile.client picks it up.
echo "[run.sh] building codex-control wheel…"
rm -rf "$HERE/_build"
mkdir -p "$HERE/_build"
if command -v uv >/dev/null 2>&1; then
    (cd "$PKG_ROOT" && uv run --with build python -m build --wheel --outdir "$HERE/_build" >/dev/null)
elif command -v python3 >/dev/null 2>&1; then
    python3 -m pip install --quiet --user build hatchling
    (cd "$PKG_ROOT" && python3 -m build --wheel --outdir "$HERE/_build" >/dev/null)
else
    echo "FAIL: need uv or python3 on PATH to build the codex-control wheel." >&2
    exit 1
fi
ls "$HERE/_build"/codex_control-*.whl >/dev/null

# 3. Build images (cached after first run).
echo "[run.sh] building docker images…"
docker build -q -f Dockerfile.server -t codex-control-server:latest . >/dev/null
docker build -q -f Dockerfile.client -t codex-control-client:latest . >/dev/null

# 4. Clean slate: remove any leftover containers and the network.
docker rm -f "$SERVER" "$CLIENT" >/dev/null 2>&1 || true
docker network rm "$NET" >/dev/null 2>&1 || true
docker network create --driver bridge "$NET" >/dev/null

cleanup() {
    docker rm -f "$SERVER" "$CLIENT" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 5. Start the server in detached mode.
echo "[run.sh] starting $SERVER…"
docker run -d --name "$SERVER" \
    --network "$NET" \
    -e WS_TOKEN_SHA256="$WS_TOKEN_SHA256" \
    -e RUST_LOG="info" \
    -v "$CODEX_HOME_HOST/auth.json:/auth-source/auth.json:ro" \
    codex-control-server:latest >/dev/null

# 6. Poll /readyz until the WS listener is up.
echo -n "[run.sh] waiting for /readyz "
for i in $(seq 1 30); do
    if docker exec "$SERVER" curl -fsS http://127.0.0.1:8765/readyz >/dev/null 2>&1; then
        echo " ready"
        break
    fi
    echo -n "."
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo " TIMED OUT"
        echo "--- server logs ---"
        docker logs "$SERVER" | tail -20
        exit 1
    fi
done

# 7. Pick the client command based on DEMO arg.
case "$DEMO" in
    smoke) CLIENT_CMD=(python3 /app/14_remote_smoke.py) ;;
    grpo)  CLIENT_CMD=(python3 /app/15_remote_grpo.py)  ;;
    *)     echo "usage: $0 [smoke|grpo]" >&2; exit 2 ;;
esac

# 8. Run the client; it inherits the WS_TOKEN; output streams to this tty.
echo "[run.sh] running $DEMO client…"
docker run --rm --name "$CLIENT" \
    --network "$NET" \
    -e REMOTE_URL="ws://$SERVER:8765" \
    -e WS_TOKEN="$WS_TOKEN" \
    -e K="${K:-4}" \
    codex-control-client:latest "${CLIENT_CMD[@]}"
