FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /bin/uv
ENV PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
COPY backend ./backend
COPY mock_supplier ./mock_supplier
COPY data ./data
COPY scripts ./scripts
RUN mkdir -p /app/.cache && chown 10001:10001 /app/.cache
USER 10001:10001
CMD ["python", "-m", "backend.server", "--host", "0.0.0.0"]
