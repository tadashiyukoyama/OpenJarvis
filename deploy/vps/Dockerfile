# syntax=docker/dockerfile:1.7

FROM node:22.23.0-slim@sha256:d9f850096136edbc402debdd8729579a288aac64574ada0ff4db26b6ae58b0b2 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN --mount=type=cache,target=/root/.npm \
    cd frontend && npm ci --ignore-scripts
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

FROM python:3.12.13-slim-bookworm@sha256:76d4b7b6305788c6b4c6a19d6a22a3921bf802e9af4d5e1e5bd771208dba74bf AS builder
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv && \
    uv export --frozen --no-dev --extra server --no-emit-project > requirements.txt && \
    uv pip install --system --no-deps -r requirements.txt
COPY src/ ./src/
COPY scripts/install/ ./scripts/install/
COPY deploy/windows/ ./deploy/windows/
COPY --from=frontend /build/src/openjarvis/server/static ./src/openjarvis/server/static/
RUN uv pip install --system --no-deps .

FROM python:3.12.13-slim-bookworm@sha256:76d4b7b6305788c6b4c6a19d6a22a3921bf802e9af4d5e1e5bd771208dba74bf
RUN groupadd --system --gid 10001 openjarvis && \
    useradd --system --uid 10001 --gid openjarvis \
      --create-home --home-dir /home/openjarvis openjarvis && \
    install -d -o openjarvis -g openjarvis /var/lib/openjarvis
COPY --from=builder /usr/local /usr/local
ENV HOME=/home/openjarvis \
    OPENJARVIS_CORE_MODE=vps \
    OPENJARVIS_HOME=/var/lib/openjarvis \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"]
ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["openjarvis.server.vps_app:create_vps_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
