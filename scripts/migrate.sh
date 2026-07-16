#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
export COGNISECT_DATABASE_URL="${DATABASE_URL}"
exec alembic upgrade head
