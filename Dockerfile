FROM python:3.12-slim

LABEL org.opencontainers.image.title="JFYI MCP Server" \
      org.opencontainers.image.description="Just For Your Information — MCP Server & Analytics Hub" \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

# 1. Cache dependencies by installing them before copying the full source code
COPY pyproject.toml README.md ./
RUN mkdir -p src/jfyi && touch src/jfyi/__init__.py && \
    pip install --upgrade pip && \
    pip install --no-cache-dir . && \
    rm -rf src/ build/ *.egg-info

# 2. Copy the actual source code
COPY src/ ./src/

# 3. Install the app itself (dependencies are already installed). Force reinstall to overwrite the dummy package.
RUN pip install --no-cache-dir --no-deps --force-reinstall .

RUN mkdir -p /data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/system/status')"

ENV JFYI_DATA_DIR=/data \
    JFYI_DB_PATH=/data/jfyi.db \
    JFYI_MCP_HOST=0.0.0.0 \
    JFYI_MCP_PORT=8080

CMD ["jfyi", "serve", "--host", "0.0.0.0", "--port", "8080"]
