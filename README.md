# PageIndex MCP

Local [FastMCP](https://github.com/modelcontextprotocol) server that exposes **PageIndex tree indexes** over CLI catalog workspaces (`./workspace/{catalog}/`) to agents in Cursor, Claude Desktop, and other MCP clients.

Forked from [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex).

## What it is

PageIndex builds a hierarchical “table of contents” tree from long documents (PDF via Docling → Markdown, or Markdown directly). This MCP lets agents:

1. List catalogs and documents under the workspace root
2. Inspect tree structure and pull page/line content
3. Insert, download, and delete indexed documents

MCP catalogs are the same filesystem layout as `run_pageindex.py --catalog …`. They are **not** `PageIndexClient` UUID / `_meta.json` workspaces.

## Tools

| Tool                     | Purpose                                                                 |
| ------------------------ | ----------------------------------------------------------------------- |
| `get_all_workspace`      | List catalog folders and a short document summary for each              |
| `get_document`           | Document metadata (name, description, page/line count, status)          |
| `get_document_structure` | Full tree structure without body text (for section discovery)           |
| `get_page_content`       | Text for page/line ranges (e.g. `5-7`, `3,8`, `12`)                     |
| `insert_page_index`      | Index from `file_path`, `url`, or `file_base64` into a catalog          |
| `download_document`      | Return stored source as base64 (prefers PDF when both PDF and MD exist) |
| `delete_document`        | Remove structure JSON and companion `.pdf` / `.md` for a `doc_id`       |

**PDF inserts** use the same pipeline as CLI `--docling`: Docling → Markdown → `md_to_tree`. Docling must be installed for PDF uploads.

## Install

Requires Python 3.12+.

```bash
pip install -e .
# PDF insert / Docling path:
pip install -e ".[docling]"
```

Copy env and set your LLM key (LiteLLM / OpenAI-compatible):

```bash
cp .env.example .env
# OPENAI_API_KEY=...
# OPENAI_BASE_URL=...   # optional gateway
```

Optional model/summary settings: copy `[config.example.yaml](config.example.yaml)` or edit `[pageindex/config.yaml](pageindex/config.yaml)`. Override path with `PAGEINDEX_CONFIG_PATH`.

## Run

### Stdio (default)

```bash
python -m pageindex.mcp
# or: pageindex-mcp
```

### Streamable HTTP

```bash
python -m pageindex.mcp --http
# LAN / IP access:
python -m pageindex.mcp --http --host 0.0.0.0
```

| Variable                   | Default              | Meaning                          |
| -------------------------- | -------------------- | -------------------------------- |
| `PAGEINDEX_WORKSPACE_ROOT` | `./workspace`        | Catalog root                     |
| `PAGEINDEX_MCP_HTTP_HOST`  | `127.0.0.1`          | Bind address (`0.0.0.0` for LAN) |
| `PAGEINDEX_MCP_HTTP_PORT`  | `8765`               | HTTP port                        |
| `PAGEINDEX_MCP_HTTP_PATH`  | `/mcp/page-index/v1` | Streamable HTTP path             |

HTTP URL: `http://<host>:8765/mcp/page-index/v1`. No HTTP auth in v1 — do not expose on untrusted networks.

## Cursor MCP config

**Remote (HTTP):**

```json
"pageindex": {
  "type": "remote",
  "url": "http://127.0.0.1:8765/mcp/page-index/v1",
  "enabled": true,
  "timeout": 300000
}
```

Replace `127.0.0.1` with your machine IP when the server is bound with `PAGEINDEX_MCP_HTTP_HOST=0.0.0.0`.

**Stdio:**

```json
{
  "mcpServers": {
    "pageindex": {
      "command": "python",
      "args": ["-m", "pageindex.mcp"],
      "cwd": "/path/to/PageIndex",
      "env": {
        "PAGEINDEX_WORKSPACE_ROOT": "/path/to/PageIndex/workspace",
        "OPENAI_API_KEY": "your_key_here"
      }
    }
  }
}
```

## Docker

Published image: [mattbeen/pageindex-mcp](https://hub.docker.com/r/mattbeen/pageindex-mcp) (includes Docling for PDF insert).

### Pull from Docker Hub

```bash
docker pull mattbeen/pageindex-mcp:0.1.0
```

### Run the image

Create host folders and a config file, then start HTTP MCP on port 8765:

```bash
mkdir -p workspace uploads
# optional: copy config.example.yaml → pageindex/config.yaml (or any path you mount)

docker run -d --name pageindex-mcp \
  -p 8765:8765 \
  -e OPENAI_API_KEY=your_key_here \
  -e OPENAI_BASE_URL=http://your-litellm-host:8080/v1 \
  -e PAGEINDEX_WORKSPACE_ROOT=/data/workspace \
  -e PAGEINDEX_CONFIG_PATH=/config/config.yaml \
  -e PAGEINDEX_MCP_HTTP_HOST=0.0.0.0 \
  -e PAGEINDEX_MCP_HTTP_PORT=8765 \
  -e PAGEINDEX_MCP_HTTP_PATH=/mcp/page-index/v1 \
  -v "$(pwd)/workspace:/data/workspace" \
  -v "$(pwd)/pageindex/config.yaml:/config/config.yaml:ro" \
  -v "$(pwd)/uploads:/data/uploads" \
  mattbeen/pageindex-mcp:0.1.0
```

- MCP URL: `http://localhost:8765/mcp/page-index/v1`
- Mounts: `workspace` → catalogs; `config.yaml` → model/summary settings; `uploads` → use `file_path` like `/data/uploads/doc.pdf`
- Image listens on `0.0.0.0:8765` inside the container

### Docker Compose (build locally)

From this repo:

```bash
cp .env.example .env
mkdir -p workspace uploads
docker compose up --build -d
```

To use the Hub image instead of building, set `image: mattbeen/pageindex-mcp:0.1.0` in `docker-compose.yml` (or pull first and retag). Same mounts and MCP URL as above.

## Workspace model

```text
./workspace/
  {catalog}/
    {stem}.md                 # Docling or uploaded Markdown
    {stem}.pdf                # optional original PDF
    {stem}_structure.json     # tree index
```

- **Catalog** — single path segment under the workspace root (no `/`, `\`, `.`, `..`).
- **`doc_id`** — document stem (filename without `_structure` / `_structure_flash`).
- **`insert_page_index`** — always persists the source into the catalog; requires a named catalog (no flat-root indexing in v1).

See `[CONTEXT.md](CONTEXT.md)` for invariants and ownership boundaries.

## Optional CLI

Same catalog layout without MCP:

```bash
python run_pageindex.py --pdf_path /path/to/doc.pdf --docling --catalog finance
python run_pageindex.py --md_path /path/to/doc.md --catalog finance
```

Flash (heuristic PDF structure, optional extra): `python run_pageindex.py --flash --pdf_path …`. Details: `[CONTEXT.md](CONTEXT.md)`, `[pageindex/flash/README.md](pageindex/flash/README.md)`.

## Attribution

Based on [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex). Upstream README, cookbooks, and examples: `[reference/](reference/)`.

Licensed under the MIT License — see [LICENSE](LICENSE).
