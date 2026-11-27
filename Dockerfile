# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_CACHE=1

# Install dependencies first for optimal layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the local package (non-editable so the venv is self-contained)
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

# --- Final stage: minimal slim runtime ---
FROM python:3.12-slim

WORKDIR /app

# Create non-root user (UID/GID 999) and strip unused build/packaging stdlib bloat
RUN groupadd -r -g 999 sonoplay \
    && useradd -r -u 999 -g sonoplay -d /app -s /sbin/nologin sonoplay \
    && mkdir -p /config \
    && chown sonoplay:sonoplay /config \
    && rm -rf /usr/local/lib/python3.12/ensurepip \
              /usr/local/lib/python3.12/idlelib \
              /usr/local/lib/python3.12/tkinter \
              /usr/local/lib/python3.12/site-packages/pip* \
              /usr/local/bin/pip*

# Copy self-contained venv and application code directly with final ownership
# (avoids a separate `chown -R` layer that would double the image size)
COPY --from=builder --chown=999:999 /app/.venv /app/.venv
COPY --chown=999:999 templates/ templates/
COPY --chown=999:999 static/ static/
COPY --chown=999:999 main.py logging_config.py version.py ./
COPY --chown=999:999 plex/ plex/
COPY --chown=999:999 dlna/ dlna/
COPY --chown=999:999 settings/ settings/
COPY --chown=999:999 utils/ utils/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HTTP_PORT=32488 \
    CONFIG_PATH=/config

EXPOSE 1910/udp 32412/udp $HTTP_PORT
VOLUME /config

USER sonoplay

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${HTTP_PORT}/health')" || exit 1

CMD ["python", "-O", "main.py"]
