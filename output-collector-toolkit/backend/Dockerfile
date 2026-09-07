ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.1
FROM ${UV_IMAGE} AS uv-source

FROM python:3.12-slim-bookworm AS base
ARG UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV LANG=C.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_INDEX_URL=${UV_INDEX_URL} \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:${PATH}"
COPY --from=uv-source /uv /uvx /usr/local/bin/
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./

FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY backend/ ./
COPY index.html /app/index.html
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--reload"]

FROM base AS production
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
COPY backend/ ./
COPY index.html /app/index.html
COPY docker/prod-entrypoint.sh /usr/local/bin/prod-entrypoint.sh
RUN groupadd --gid 10001 collector \
    && useradd --uid 10001 --gid collector --no-create-home collector \
    && mkdir -p /app/backend/data \
    && chown collector:collector /app/backend/data
USER collector
EXPOSE 8000
CMD ["sh", "/usr/local/bin/prod-entrypoint.sh"]
