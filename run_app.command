#!/bin/bash
# Quick launcher for backend (uvicorn) and frontend (npm dev) with logs.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
mkdir -p "$LOG_DIR"

# Activate local venv if present
if [ -d "$DIR/.venv" ]; then
  source "$DIR/.venv/bin/activate"
fi

echo "Starting backend (uvicorn backend.main:app) -> $BACKEND_LOG"
(cd "$DIR/backend" && uvicorn main:app --host 0.0.0.0 --port 8000 >> "$BACKEND_LOG" 2>&1) &
BACK_PID=$!
echo $BACK_PID > "$LOG_DIR/backend.pid"

echo "Starting frontend (npm run dev -- --host --port 5173) -> $FRONTEND_LOG"
(
  cd "$DIR/frontend"
  if [ ! -d node_modules ]; then
    echo "Installing frontend deps..."
    npm install >> "$FRONTEND_LOG" 2>&1
  fi
  npm run dev -- --host --port 5173 >> "$FRONTEND_LOG" 2>&1
) &
FRONT_PID=$!
echo $FRONT_PID > "$LOG_DIR/frontend.pid"

echo "PIDs: backend=$BACK_PID frontend=$FRONT_PID"
echo "Logs: $BACKEND_LOG / $FRONTEND_LOG"
echo "Opening http://localhost:5173 ..."
open "http://localhost:5173" >/dev/null 2>&1 || true

# Keep terminal open with log tail; stop both on Ctrl+C
trap 'echo "Stopping..."; kill $BACK_PID $FRONT_PID 2>/dev/null || true; exit 0' INT TERM
tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
