# syntax=docker/dockerfile:1
# Multi-stage build: React/Vite SPA -> Python 3.13 runtime serving API + WebSocket relay + static SPA.

FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    STATIC_DIR=/app/static
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY src ./src
COPY --from=web /web/dist ./static
RUN date -u +%Y%m%d-%H%M%S > /app/BUILD_ID \
    && useradd --system --uid 10001 --no-create-home app \
    && chown -R app /app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "concierge.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--ws-ping-interval", "20", "--ws-ping-timeout", "30", "--no-server-header"]
