#!/usr/bin/env sh
set -eu

python /app/scripts/wait_for_postgres.py
alembic -c /app/packages/db/alembic.ini upgrade head || true
python /app/scripts/seed_demo.py || true
