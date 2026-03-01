"""
apps/api/tasks.py

Celery task definitions.
For the demo, inference runs via FastAPI BackgroundTasks.
These stubs exist so the worker starts cleanly.
"""

from celery_app import celery_app
import logging

log = logging.getLogger(__name__)


@celery_app.task(name="tasks.run_inference", bind=True, max_retries=2)
def run_inference_task(self, job_id: str):
    """
    Placeholder for async inference via Celery.
    Currently inference is handled by FastAPI BackgroundTasks in main.py.
    This task exists so the worker container has something to register.
    """
    log.info(f"[celery] run_inference_task called for job {job_id}")
    return {"job_id": job_id, "status": "delegated_to_background_task"}
