# Optional reproducible local runtime (Windows/macOS/Linux via Docker Desktop).
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && pip install --no-cache-dir "uv>=0.9.17"
WORKDIR /app
COPY . .
RUN uv sync --frozen
ENV PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
EXPOSE 8000 3000
CMD ["uv", "run", "start-app", "--local"]
