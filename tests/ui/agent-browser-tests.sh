#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/tests/ui/artifacts"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/family-book-ui.XXXXXX")"
PORT="${PORT:-8765}"
BASE_URL="http://127.0.0.1:${PORT}"

mkdir -p "${ARTIFACT_DIR}"

export SECRET_KEY="test-secret-key-not-for-production-use-1234567890"
export FERNET_KEY="dGVzdC1mZXJuZXQta2V5LW5vdC1mb3ItcHJvZHVjdGlvbg=="
export BASE_URL
export DATA_DIR="${TMP_DIR}/data"
export DATABASE_URL="sqlite:///${TMP_DIR}/family-book-ui.db"
export AGENT_BROWSER_SESSION="fb"
export AGENT_BROWSER_SESSION_NAME="fbui"
export AGENT_BROWSER_SOCKET_DIR="/tmp/fb-sock-${PORT}"
export HOME="${TMP_DIR}/home"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
  agent-browser close >/dev/null 2>&1 || true
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

failures=0

record_failure() {
  echo "FAIL: $1"
  failures=$((failures + 1))
}

record_success() {
  echo "PASS: $1"
}

cd "${ROOT_DIR}"
mkdir -p "${DATA_DIR}"
mkdir -p "${HOME}"
mkdir -p "${AGENT_BROWSER_SOCKET_DIR}"

.venv/bin/python - <<'PY'
import asyncio

from app.database import engine
from app.models.base import Base


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(main())
PY

.venv/bin/python -m uvicorn tests.ui.phase1_app:app --host 127.0.0.1 --port "${PORT}" >"${ARTIFACT_DIR}/agent-browser-server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 50); do
  if python3 - <<'PY' >/dev/null 2>&1
import json
import os
import urllib.request

with urllib.request.urlopen(f"{os.environ['BASE_URL']}/health", timeout=1) as response:
    json.load(response)
PY
  then
    break
  fi
  sleep 0.2
done

agent-browser open "${BASE_URL}/health" >/dev/null
agent-browser screenshot "${ARTIFACT_DIR}/health.png" >/dev/null

if python3 - <<'PY'
import json
import os
import urllib.request

with urllib.request.urlopen(f"{os.environ['BASE_URL']}/health", timeout=3) as response:
    payload = json.load(response)

assert payload["status"] == "ok"
assert payload["db"] == "connected"
assert isinstance(payload["persons_count"], int)
PY
then
  record_success "health endpoint returns valid JSON"
else
  record_failure "health endpoint returns valid JSON"
fi

agent-browser open "${BASE_URL}/login" >/dev/null
agent-browser screenshot "${ARTIFACT_DIR}/login.png" >/dev/null

if agent-browser get html body | grep -qi "<form"; then
  record_success "login page exposes a form"
else
  record_failure "login page exposes a form"
fi

agent-browser open "${BASE_URL}/api/persons" >/dev/null || true
agent-browser screenshot "${ARTIFACT_DIR}/protected-route.png" >/dev/null

current_url="$(agent-browser get url)"
if [[ "${current_url}" == "${BASE_URL}/login"* ]]; then
  record_success "unauthenticated protected route redirects to login"
else
  record_failure "unauthenticated protected route redirects to login"
fi

if (( failures > 0 )); then
  echo "agent-browser checks completed with ${failures} failure(s). Screenshots: ${ARTIFACT_DIR}"
  exit 1
fi

echo "agent-browser checks passed. Screenshots: ${ARTIFACT_DIR}"
