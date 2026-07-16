#!/bin/sh
set -eu

exec uvicorn cognisect.api:build_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
  --no-access-log
