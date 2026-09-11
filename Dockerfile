# WenQu backend image.  The business database is intentionally external to
# this image; configure MYSQL_* and MANAGEMENT_MYSQL_* at deploy time.
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin wenqu \
    && mkdir -p /app/data /app/logs \
    && chown -R wenqu:wenqu /app

COPY pyproject.toml uv.lock ./
COPY app ./app
COPY scripts ./scripts

RUN uv sync --frozen --no-dev

RUN chown -R wenqu:wenqu /app
USER wenqu

EXPOSE 4400

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4400/health', timeout=3)"]

CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4400"]
