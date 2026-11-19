# syntax=docker/dockerfile:1
# --- Stage 1: build the React/Vite SPA -----------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
# --ignore-scripts: no install-time scripts/telemetry from transitive deps
RUN npm ci --no-audit --no-fund --ignore-scripts
COPY web/ ./
RUN npm run build

# --- Stage 2: runtime (FastAPI + ffmpeg compositor + SPA) ----------------------------------------
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    STATIC_DIR=/app/static

# ffmpeg = spot compositor encoder / audio mix / loudness. Caption fonts (DejaVu: Latin, Cyrillic, Greek) ship in the package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin spotlight

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .
# OpenCV (headless) measures how much a generated clip really moves; a broken wheel must fail the build, not the first render
RUN python -c "import cv2; print('opencv', cv2.__version__)"
COPY --from=web /web/dist /app/static

USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"
CMD ["sh", "-c", "exec uvicorn spotlight.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
