# Multi-stage build: the dashboard is built once and served by Caddy; the API and
# the worker share one non-root Python image.

# ---- dashboard
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- python runtime (api + worker)
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
RUN useradd --create-home --uid 10001 gk
WORKDIR /app
COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt alembic==1.14.0
COPY backend/ backend/
COPY worker/ worker/
RUN mkdir -p /app/models && chown gk /app/models
USER gk
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "30", "--access-logfile", "-", "backend.app:create_app()"]

# ---- static files for caddy
FROM caddy:2.8-alpine AS caddy
COPY --from=web /web/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
