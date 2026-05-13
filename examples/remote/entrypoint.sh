#!/bin/sh
# Server entrypoint: copy the read-only auth.json into the writable
# CODEX_HOME, then exec the app-server with WS listener.
set -eu

if [ -f /auth-source/auth.json ]; then
    cp /auth-source/auth.json "${CODEX_HOME}/auth.json"
    chmod 600 "${CODEX_HOME}/auth.json"
fi

: "${WS_TOKEN_SHA256:?must set WS_TOKEN_SHA256}"

exec codex app-server \
    --listen ws://0.0.0.0:8765 \
    --ws-auth capability-token \
    --ws-token-sha256 "${WS_TOKEN_SHA256}"
