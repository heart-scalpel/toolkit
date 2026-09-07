#!/usr/bin/env sh
set -eu
cd /app/backend
mkdir -p "${COLLECTOR_DATA_DIR:-/app/backend/data}"
# The app lifespan runs Alembic migrations before serving registration and login.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
