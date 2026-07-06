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

# ---- frontend stage: pull the latest built frontend release ----
# Downloads the newest release of omnishare_frontend and unpacks the
# `frontend-dist-*.tar.gz` asset into /frontend/dist. The archive is packed
# with `tar -C dist .`, so its files sit at the archive root and are extracted
# back into a fresh `dist/` directory here.
FROM alpine:3.20 AS frontend

RUN apk add --no-cache curl jq tar

WORKDIR /frontend

# Which repo to pull the frontend from.
ARG FRONTEND_REPO=frum1/omnishare_frontend
# Bump this (CI passes the git tag) to bust the layer cache so every image
# build re-fetches the current latest release instead of a cached one.
ARG CACHEBUST=latest

# An optional `frontend_token` build secret authorizes access while the
# frontend repo is still private. Once it's public no secret is needed —
# an absent/empty secret transparently falls back to unauthenticated calls.
RUN --mount=type=secret,id=frontend_token \
    set -eu; \
    if [ -s /run/secrets/frontend_token ]; then \
        AUTH="Authorization: Bearer $(cat /run/secrets/frontend_token)"; \
    else \
        AUTH="X-No-Auth: 1"; \
    fi; \
    api="https://api.github.com/repos/${FRONTEND_REPO}/releases/latest"; \
    asset_url="$(curl -fsSL -H "$AUTH" -H "Accept: application/vnd.github+json" "$api" \
        | jq -r '.assets[] | select(.name | endswith(".tar.gz")) | .url' | head -n1)"; \
    [ -n "$asset_url" ] || { echo "No .tar.gz asset found on latest release" >&2; exit 1; }; \
    curl -fsSL -H "$AUTH" -H "Accept: application/octet-stream" "$asset_url" -o /tmp/frontend.tar.gz; \
    mkdir -p dist; \
    tar -xzf /tmp/frontend.tar.gz -C dist; \
    rm /tmp/frontend.tar.gz

# ---- runtime stage: slim image with just the venv + source ----
FROM python:3.12-slim-bookworm

WORKDIR /app

# Bring in the ready-made virtualenv from the build stage.
COPY --from=builder /app/.venv /app/.venv

# Application source.
COPY main.py ./
COPY app ./app
COPY scripts ./scripts

# Built frontend fetched from the latest omnishare_frontend release. Served by
# the app from /app/dist (see app/main.py).
COPY --from=frontend /frontend/dist ./dist

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"

CMD ["python", "main.py"]
