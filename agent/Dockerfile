FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy only dependency files first
COPY pyproject.toml .
COPY uv.lock .

# Install deps (cached unless lock changes)
RUN uv sync --frozen --no-dev

COPY src src
COPY main.py .

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "main.py"]
