#!/usr/bin/env sh
set -eu

cd /app/backend
mkdir -p "${COLLECTOR_DATA_DIR:-/app/backend/data}"

# The checkout is bind-mounted; keep the container's virtualenv in sync.
uv sync --locked

# The application runs database migrations before serving requests.
exec uv run --no-sync uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --reload \
    --reload-exclude '.venv/*' \
    --reload-exclude 'data/*'
