#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
export COGNISECT_DATABASE_URL="${DATABASE_URL}"
alembic upgrade head
python scripts/setup_checkpoints.py
