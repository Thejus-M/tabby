FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project

COPY src ./src
RUN uv sync --locked
# OCR models ship inside the rapidocr wheel; load them once at build time to fail early if anything is missing.
RUN uv run --no-sync python -c "from tabby.scan.ocr import load_engine; load_engine()"

ENV DATABASE_PATH=/data/tabby.db
VOLUME /data
EXPOSE 8000
# Single worker: the rate limiter is in-process memory and one OCR model (~300 MB) is loaded per process.
CMD ["uv", "run", "--no-sync", "uvicorn", "tabby.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
