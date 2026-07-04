# ---- build stage: resolve and install dependencies with uv ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install only the dependencies first so this layer stays cached as long as
# the lockfile doesn't change. --no-install-project skips building the app
# itself (it's run from source, not installed as a package).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# ---- runtime stage: slim image with just the venv + source ----
FROM python:3.12-slim-bookworm

WORKDIR /app

# Bring in the ready-made virtualenv from the build stage.
COPY --from=builder /app/.venv /app/.venv

# Application source.
COPY main.py ./
COPY app ./app
COPY scripts ./scripts

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"

CMD ["python", "main.py"]
