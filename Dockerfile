FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock* README.md ./

# Install dependencies (including optional LLM dependencies)
RUN uv sync --frozen --no-dev --extra llm

# Copy application code
COPY . .

# Set environment to use the venv and run the bot
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
CMD ["uv", "run", "--frozen", "python", "-m", "envoy.main"]

