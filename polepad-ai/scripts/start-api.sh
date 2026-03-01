#!/usr/bin/env sh
set -eu

python /app/scripts/wait_for_postgres.py
exec uvicorn main:app --host 0.0.0.0 --port 8000
