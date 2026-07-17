#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
. "$(dirname "$0")/database_url.sh"
normalize_database_url
alembic upgrade head
python scripts/setup_checkpoints.py
