"""
apps/api/celery_app.py

Celery application for async job processing.
The worker container in docker-compose.yml runs:
    celery -A celery_app worker --loglevel=info --concurrency=2

For the hackathon demo the pipeline runs via FastAPI BackgroundTasks
(no Celery needed). This file just makes the worker container start
without crashing so docker compose up doesn't fail.
"""

import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "polepad",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # For demo: tasks expire after 1 hour
    result_expires=3600,
    # Worker settings
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# Alias so `celery -A celery_app worker` finds the app
app = celery_app
