#!/bin/sh
# Gunicorn direct opstarten.
# Als de DB er niet is, toont de app gewoon db_offline.html.
# /healthz geeft aan of de DB bereikbaar is.
set -e

export TZ="${TZ:-Europe/Amsterdam}"
export HOME=/tmp

echo "Mooindag! Gunicorn starten (TZ=${TZ})..."

exec gunicorn app:app \
    --bind "0.0.0.0:8080" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout 30 \
    --pid /tmp/gunicorn.pid \
    --worker-tmp-dir /tmp \
    --access-logfile - \
    --error-logfile -
