# PageIndex MCP (HTTP) — Docling-enabled image for PDF insert pipeline
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PAGEINDEX_WORKSPACE_ROOT=/data/workspace \
    PAGEINDEX_CONFIG_PATH=/config/config.yaml \
    PAGEINDEX_MCP_HTTP_HOST=0.0.0.0 \
    PAGEINDEX_MCP_HTTP_PORT=8765 \
    PAGEINDEX_MCP_HTTP_PATH=/mcp/page-index/v1

WORKDIR /app

# System libs commonly needed by PyMuPDF / Docling / OCR stacks.
# HTTPS: this network's URL filter blocks apt's plain-HTTP user agent.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md requirements.txt ./
COPY pageindex ./pageindex

RUN pip install --upgrade pip \
    && pip install -e ".[docling]"

RUN mkdir -p /data/workspace /config /data/uploads

EXPOSE 8765

CMD ["python", "-m", "pageindex.mcp", "--http"]
