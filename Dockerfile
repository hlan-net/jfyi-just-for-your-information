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
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

COPY --from=builder /dist/*.whl /tmp/
RUN pip install --upgrade pip && pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

RUN mkdir -p /data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/profile/rules')"

ENV JFYI_DATA_DIR=/data \
    JFYI_DB_PATH=/data/jfyi.db \
    JFYI_MCP_HOST=0.0.0.0 \
    JFYI_MCP_PORT=8080

CMD ["jfyi", "serve", "--host", "0.0.0.0", "--port", "8080"]
