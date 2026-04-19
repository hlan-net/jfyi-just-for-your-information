FROM python:3.12-slim AS builder

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --upgrade pip && \
    pip install --no-cache-dir build && \
    python -m build --wheel --outdir /dist

FROM python:3.12-slim

LABEL org.opencontainers.image.title="JFYI MCP Server" \
      org.opencontainers.image.description="Just For Your Information — MCP Server & Analytics Hub" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install runtime dependencies
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir "mcp>=1.0.0" "fastapi>=0.115.0" "uvicorn[standard]>=0.30.0" \
        "httpx>=0.27.0" "sqlalchemy>=2.0.0" "aiosqlite>=0.20.0" \
        "pydantic>=2.0.0" "pydantic-settings>=2.0.0" "typer>=0.12.0" "rich>=13.0.0"

COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl

# Create data directory for PVC mount
RUN mkdir -p /data

# Expose ports
EXPOSE 8080 3000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/profile/rules')"

ENV JFYI_DATA_DIR=/data \
    JFYI_DB_PATH=/data/jfyi.db \
    JFYI_VECTOR_DB_PATH=/data/chromadb \
    JFYI_MCP_HOST=0.0.0.0 \
    JFYI_MCP_PORT=8080 \
    JFYI_DASHBOARD_HOST=0.0.0.0 \
    JFYI_DASHBOARD_PORT=3000

CMD ["jfyi", "serve", "--host", "0.0.0.0", "--port", "8080"]
