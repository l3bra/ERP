#!/usr/bin/env bash
# Запуск только API (без открытия браузера). Сервер Linux.
set -e
cd "$(dirname "$0")"

if [ -f backend/venv/bin/python ]; then
    PYTHON="$(pwd)/backend/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    echo "Python 3 not found." >&2
    exit 1
fi

if [ ! -f backend/main.py ]; then
    echo "Missing backend/main.py next to start_server.sh." >&2
    exit 1
fi

cd backend
exec "$PYTHON" -m uvicorn main:app --host 127.0.0.1 --port 8000
