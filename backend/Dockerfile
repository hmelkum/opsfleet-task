FROM python:3.12-slim AS base

WORKDIR /app

# Install uv
RUN pip install uv

# Copy only dependency files first
COPY pyproject.toml .
COPY uv.lock .

ENV PATH="/app/.venv/bin:$PATH"


# Applies Alembic migrations, then exits
FROM base AS migration

# Install deps (cached unless lock changes)
RUN uv sync --frozen --no-dev --group migrations

COPY src src
COPY migrations migrations
COPY alembic.ini .

CMD ["alembic", "upgrade", "head"]


# The API: gateway, artifacts and ecommerce modules with their MCP servers
FROM base AS backend

# Install deps (cached unless lock changes)
RUN uv sync --frozen --no-dev

COPY src src
COPY main.py .

CMD ["python", "main.py"]
