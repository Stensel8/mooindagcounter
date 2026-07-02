#!/bin/sh
# Mooindag! Gunicorn + UvicornWorker (ASGI) opstarten.
set -e

export TZ="${TZ:-Europe/Amsterdam}"
export HOME=/tmp

echo "Mooindag! Gunicorn+Uvicorn starten (TZ=${TZ})..."

exec gunicorn app:app \
    -k uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:8080" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout 30 \
    --forwarded-allow-ips "*" \
    --pid /tmp/gunicorn.pid \
    --worker-tmp-dir /tmp \
    --access-logfile - \
    --error-logfile -
