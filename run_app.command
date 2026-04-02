#!/bin/bash
# Quick launcher for backend (uvicorn) and frontend (npm dev) with logs.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
mkdir -p "$LOG_DIR"

# Pick ports (prefer defaults; fall back to a free port if occupied)
choose_port() {
  local preferred="$1"
  python3 - "$preferred" <<'PY'
import socket, sys
preferred = int(sys.argv[1])

def is_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("", port))
    except OSError:
        s.close()
        return False
    s.close()
    return True

if is_free(preferred):
    print(preferred)
else:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    print(port)
PY
}

BACKEND_PORT="$(choose_port "${BACKEND_PORT:-8000}")"
FRONTEND_PORT="$(choose_port "${FRONTEND_PORT:-5173}")"

# Activate local venv if present
if [ -d "$DIR/.venv" ]; then
  source "$DIR/.venv/bin/activate"
fi

echo "Using backend port: $BACKEND_PORT"
echo "Using frontend port: $FRONTEND_PORT"

echo "Starting backend (uvicorn backend.main:app) -> $BACKEND_LOG"
(cd "$DIR" && uvicorn backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" >> "$BACKEND_LOG" 2>&1) &
BACK_PID=$!
echo $BACK_PID > "$LOG_DIR/backend.pid"

echo "Starting frontend (npm run dev -- --host --port $FRONTEND_PORT) -> $FRONTEND_LOG"
(
  cd "$DIR/frontend"
  if [ ! -d node_modules ]; then
    echo "Installing frontend deps..."
    npm install >> "$FRONTEND_LOG" 2>&1
  fi
  VITE_API_URL="http://localhost:$BACKEND_PORT" VITE_WS_URL="ws://localhost:$BACKEND_PORT/ws" npm run dev -- --host --port "$FRONTEND_PORT" >> "$FRONTEND_LOG" 2>&1
) &
FRONT_PID=$!
echo $FRONT_PID > "$LOG_DIR/frontend.pid"

echo "PIDs: backend=$BACK_PID frontend=$FRONT_PID"
echo "Logs: $BACKEND_LOG / $FRONTEND_LOG"
echo "Opening http://localhost:$FRONTEND_PORT ..."
open "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1 || true

# Keep terminal open with log tail; stop both on Ctrl+C
trap 'echo "Stopping..."; kill $BACK_PID $FRONT_PID 2>/dev/null || true; exit 0' INT TERM
tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
