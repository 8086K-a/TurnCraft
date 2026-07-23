#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "Starting backend..."
uvicorn agent.api.app:app --host 0.0.0.0 --port 18082 --reload &
BACKEND_PID=$!

echo "Starting frontend..."
cd frontend && npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
