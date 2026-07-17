#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
. "$(dirname "$0")/database_url.sh"
normalize_database_url

exec uvicorn cognisect.api:build_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
  --no-access-log
