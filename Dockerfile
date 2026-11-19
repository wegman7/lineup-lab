# One image: build the React app, then serve it and the API from FastAPI (technical spec §7).
# Build context is the repo root:  docker build -t lineup-lab .

FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
# Same npm that wrote package-lock.json; other versions disagree on optional wasm deps.
RUN npm install -g npm@11.6.2 --silent && npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /app/backend
# Dependencies first (cached layer), then the package. No dev or ingest groups.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-default-groups --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-default-groups --no-editable
COPY --from=frontend /frontend/dist /app/static
COPY data/stats.duckdb /app/data/stats.duckdb
# Files stay root-owned (the app only reads them); run as an unprivileged user.
RUN useradd --system app
USER app
ENV PATH="/app/backend/.venv/bin:$PATH" \
    STATS_DB_PATH=/app/data/stats.duckdb \
    STATIC_DIR=/app/static
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn lineup_lab.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]
