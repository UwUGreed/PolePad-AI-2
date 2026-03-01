#!/usr/bin/env sh
set -eu

python /app/scripts/wait_for_postgres.py
exec sh -c "celery -A celery_app worker --loglevel=info --concurrency=2 || (echo 'Celery worker failed to start, running in stub mode' && tail -f /dev/null)"
