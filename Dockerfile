# syntax=docker/dockerfile:1.7
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        poppler-utils \
        ghostscript \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./

# Build a dependency manifest from pyproject, so dependency install is decoupled from app source changes.
RUN python - <<'PY'
import tomllib
from pathlib import Path

deps = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
Path("requirements.docker.txt").write_text("\n".join(deps) + "\n", encoding="utf-8")
PY

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip \
    && python -m pip install -r requirements.docker.txt

COPY app ./app
COPY main.py ./main.py

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
