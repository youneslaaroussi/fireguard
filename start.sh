#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8100"
FRONTEND_URL="http://127.0.0.1:5174"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python not found: $PYTHON_BIN" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found" >&2
  exit 1
fi

backend_pid=""
frontend_pid=""

cleanup() {
  trap - INT TERM EXIT
  if [[ -n "$frontend_pid" ]]; then
    kill "$frontend_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$backend_pid" ]]; then
    kill "$backend_pid" >/dev/null 2>&1 || true
  fi
  wait "$frontend_pid" >/dev/null 2>&1 || true
  wait "$backend_pid" >/dev/null 2>&1 || true
}

trap cleanup INT TERM EXIT

cd "$ROOT_DIR"
"$PYTHON_BIN" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload &
backend_pid="$!"

(
  cd "$ROOT_DIR/web"
  npm run dev
) &
frontend_pid="$!"

echo "Backend:  http://$BACKEND_HOST:$BACKEND_PORT"
echo "Frontend: $FRONTEND_URL"
echo "Press Ctrl+C to stop both."

while true; do
  if ! kill -0 "$backend_pid" >/dev/null 2>&1; then
    wait "$backend_pid"
    exit "$?"
  fi
  if ! kill -0 "$frontend_pid" >/dev/null 2>&1; then
    wait "$frontend_pid"
    exit "$?"
  fi
  sleep 1
done
