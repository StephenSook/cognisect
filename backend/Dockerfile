FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv==0.10.9

COPY pyproject.toml uv.lock ./
COPY backend ./backend
RUN uv sync --frozen --no-dev --no-editable

COPY alembic.ini ./
COPY scripts ./scripts

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
CMD ["./scripts/run-backend.sh"]
