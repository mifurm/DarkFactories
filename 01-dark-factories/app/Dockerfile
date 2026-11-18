# syntax=docker/dockerfile:1
# ---- stage 1: build the React/Vite SPA -------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- stage 2: Python runtime (FastAPI serves the API and the built SPA) -----------------------------
FROM python:3.13-slim AS runtime
ARG BUILD_ID=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv/src \
    BUILD_ID=${BUILD_ID} \
    PORT=8000
WORKDIR /srv
RUN useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin nightshift
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY src/ ./src/
COPY --from=web /web/dist ./src/nightshift/static
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz',timeout=4)" || exit 1
CMD ["sh", "-c", "exec python -m uvicorn nightshift.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
