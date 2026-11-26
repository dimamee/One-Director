# One Director — container image (API and dashboard share one image).
#
#   * slim base image with an exact tag; TODO before the pilot: pin by digest
#     (python:3.11.x-slim-trixie@sha256:...), see README;
#   * multi-stage: build tools and pip caches stay in the builder stage;
#   * dependencies only from the hash-locked requirements.txt, --no-deps;
#   * runs as an unprivileged user, code is owned by root (read-only for app);
#   * no secrets in the image: they arrive as environment variables at run time.
ARG PYTHON_IMAGE=python:3.11.14-slim-trixie

# ---------------------------------------------------------------- builder ---
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes --no-deps -r requirements.txt

# ---------------------------------------------------------------- runtime ---
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/app/src" \
    HOME="/tmp" \
    DEMO_MODE="true"

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY src/ ./src/
COPY app/ ./app/

USER 10001:10001
EXPOSE 8000

# /health returns only {"status": "ok"} (specs/api-contract.md).
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

# The ASGI app (one_director.api.main:app) is implemented by the backend agent
# (specs/agents/07-backend.md); until then the container does not start.
CMD ["uvicorn", "one_director.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--no-server-header", "--no-access-log"]
