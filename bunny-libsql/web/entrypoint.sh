#!/bin/sh
# Mooindag! Gunicorn + UvicornWorker (ASGI) opstarten.
set -e

export TZ="${TZ:-Europe/Amsterdam}"
export HOME=/tmp

# Toon of de database-variabelen gezet zijn, maar NOOIT hun waarde:
# container-logs zijn zichtbaar in het Bunny-dashboard en het auth-token
# geeft schrijftoegang tot de database.
is_set() { if [ -n "$1" ]; then echo "ingesteld"; else echo "niet ingesteld"; fi; }
echo "=== Omgevingsvariabelen (DB gerelateerd) ==="
echo "BUNNY_DATABASE_URL: $(is_set "${BUNNY_DATABASE_URL:-}")"
echo "LIBSQL_URL: $(is_set "${LIBSQL_URL:-}")"
echo "BUNNY_DATABASE_AUTH_TOKEN: $(is_set "${BUNNY_DATABASE_AUTH_TOKEN:-}")"
echo "LIBSQL_AUTH_TOKEN: $(is_set "${LIBSQL_AUTH_TOKEN:-}")"
echo "BUNNYNET_MC_REGION: ${BUNNYNET_MC_REGION:-niet ingesteld}"
echo ""

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
