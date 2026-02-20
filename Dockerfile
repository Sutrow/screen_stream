FROM ghcr.io/astral-sh/uv:0.9.2-python3.14-bookworm-slim AS app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies
COPY pyproject.toml uv.lock* ./
RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-cache

COPY . .
EXPOSE 8080
CMD ["uv", "run", "uvicorn", "app.server:app", "--port", "8080", "--host", "0.0.0.0"]