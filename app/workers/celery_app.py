from app.core.config import settings

try:
    from celery import Celery
except Exception:  # pragma: no cover - fallback for constrained environments
    class _TaskWrapper:
        def __init__(self, fn):
            self._fn = fn

        def __call__(self, *args, **kwargs):
            return self._fn(*args, **kwargs)

        def delay(self, *args, **kwargs):
            return self._fn(*args, **kwargs)

    class Celery:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            self.conf = {}

        def task(self, name: str | None = None):
            def _decorator(fn):
                return _TaskWrapper(fn)

            return _decorator


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
