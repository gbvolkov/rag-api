from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.api.api_v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.init_db import init_db


app = FastAPI(
    title=settings.app_name,
    default_response_class=ORJSONResponse,
    openapi_url=f"{settings.api_v1_str}/openapi.json",
)
app.include_router(api_router, prefix=settings.api_v1_str)


@app.on_event("startup")
async def startup_event() -> None:
    configure_logging()
    await init_db()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {"service": settings.app_name, "api": settings.api_v1_str}


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
