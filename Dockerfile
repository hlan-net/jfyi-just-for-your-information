FROM python:3.14-slim@sha256:5b3879b6f3cb77e712644d50262d05a7c146b7312d784a18eff7ff5462e77033

LABEL org.opencontainers.image.title="JFYI MCP Server" \
      org.opencontainers.image.description="Just For Your Information — MCP Server & Analytics Hub" \
      org.opencontainers.image.licenses="Apache-2.0"

# Create a non-root user with a known UID so pwd.getpwuid() works when
# Kubernetes applies securityContext.runAsUser=1000.
RUN addgroup --system --gid 1000 jfyi && \
    adduser --system --uid 1000 --gid 1000 --home /home/jfyi --shell /bin/false jfyi

WORKDIR /app

# 1. Cache dependencies by installing them before copying the full source code.
# pyproject.toml is the unmodified repo file here, so this layer stays cached
# across releases. The version is injected later, after this layer.
COPY pyproject.toml README.md ./
RUN mkdir -p src/jfyi && touch src/jfyi/__init__.py && \
    pip install --upgrade pip && \
    pip install --no-cache-dir . && \
    rm -rf src/ build/ *.egg-info

# 3. Copy the actual source code
COPY src/ ./src/

# 4. Inject the release version, then reinstall the app (deps stay cached).
ARG VERSION=0.0.0-dev
RUN sed -i "s/0.0.0-dev/${VERSION}/g" pyproject.toml && \
    pip install --no-cache-dir --no-deps --force-reinstall .

RUN mkdir -p /data/models && chown -R jfyi:jfyi /data /app /home/jfyi

USER jfyi

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/system/status')"

ENV JFYI_DATA_DIR=/data \
    JFYI_DB_PATH=/data/jfyi.db \
    JFYI_MCP_HOST=0.0.0.0 \
    JFYI_MCP_PORT=8080 \
    JFYI_SENTENCE_TRANSFORMERS_HOME=/data/models \
    HOME=/home/jfyi

CMD ["jfyi", "serve", "--host", "0.0.0.0", "--port", "8080"]
