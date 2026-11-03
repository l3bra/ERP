#!/usr/bin/env bash
# Запуск только API (без открытия браузера). Сервер Linux.
#
# Слушает все сетевые интерфейсы (0.0.0.0), чтобы к приложению можно было
# подключаться из локальной сети по адресу http://<IP-сервера>:8000/
#
# Хост и порт переопределяются переменными окружения:
#   ERP_HOST=127.0.0.1 ERP_PORT=9000 ./start_server.sh
set -e
cd "$(dirname "$0")"

HOST="${ERP_HOST:-0.0.0.0}"
PORT="${ERP_PORT:-8000}"

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
exec "$PYTHON" -m uvicorn main:app --host "$HOST" --port "$PORT"
