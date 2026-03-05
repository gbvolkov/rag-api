from app.core.config import settings

try:
    from celery import Celery
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "Celery dependency is required for rag-api worker module. Install celery or disable async worker endpoints."
    ) from exc


celery_app = Celery("rag_api", broker=settings.redis_url, backend=settings.redis_url)
if hasattr(celery_app, "conf") and hasattr(celery_app.conf, "update"):
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        result_expires=settings.celery_result_expires_seconds,
    )

# Ensure task decorators execute when the worker boots with
# `-A app.workers.celery_app.celery_app`.
from app.workers import tasks as _tasks  # noqa: F401,E402
