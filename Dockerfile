FROM ghcr.io/astral-sh/uv:0.9.2-python3.14-bookworm-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PYTHON_PREFERENCE=only-managed

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-editable

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM gcr.io/distroless/cc-debian12

COPY --from=builder /python       /python
COPY --from=builder /app/.venv    /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

USER nonroot

CMD ["/app/.venv/bin/uvicorn", "app.server:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1"]