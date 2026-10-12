# syntax=docker/dockerfile:1.7
# R2M Control Plane: platform API (private 127.0.0.1:8000) + Control Plane web app (public :3000).
# The OpsPilot agent is NOT in this image; it runs in its own container (Dockerfile.opspilot).

FROM node:22.12.0-bookworm-slim AS node-runtime

FROM node-runtime AS web-build
ARG NEXT_PUBLIC_CONTROL_URL=http://localhost:3000
ARG NEXT_PUBLIC_DESK_URL=http://localhost:3001
ENV NEXT_PUBLIC_R2M_APP=control NEXT_PUBLIC_CONTROL_URL=$NEXT_PUBLIC_CONTROL_URL \
    NEXT_PUBLIC_DESK_URL=$NEXT_PUBLIC_DESK_URL NEXT_TELEMETRY_DISABLED=1
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.8-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY python/pyproject.toml /app/python/pyproject.toml
COPY python/r2m_platform/ /app/python/r2m_platform/
RUN pip install --no-cache-dir /app/python
COPY db/ /app/db/
COPY scripts/ /app/scripts/
COPY docker/ /app/docker/
COPY --from=web-build /src/web/.next/standalone /app/web
COPY --from=web-build /src/web/.next/static /app/web/.next/static
COPY --from=web-build /src/web/public /app/web/public

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin r2m \
    && chmod 0555 /app/docker/entrypoint.sh
USER r2m
EXPOSE 3000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
