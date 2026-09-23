#!/usr/bin/env bash
set -euo pipefail

if [ ! -x .venv/bin/uvicorn ]; then
  echo 'Сначала установите зависимости API: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt'
  exit 1
fi

.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM

npm run dev -- --host 127.0.0.1 --port 3000
