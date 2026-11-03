#!/usr/bin/env bash
# Сборка фронтенда (при необходимости) и запуск приложения. Сервер Linux.
set -e
cd "$(dirname "$0")"

if [ ! -f frontend/dist/index.html ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "Node.js/npm не найдены: соберите фронтенд вручную" >&2
        echo "  cd frontend && npm install && npm run build" >&2
        exit 1
    fi
    echo "Сборка фронтенда…"
    (cd frontend && { [ -d node_modules ] || npm install; } && npm run build)
fi

exec ./start_server.sh
