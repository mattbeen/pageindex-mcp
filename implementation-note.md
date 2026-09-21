# Implementation note: Docling CLI + multi-catalog

Running log of decisions made while implementing Docling and catalog support that were not fully spelled out in the product README.

## Decisions

### Optional Docling dependency

Docling is heavy (layout models, OCR stack). It is **not** in the default `requirements.txt` / `pyproject.toml` dependencies. Install via `pip install -e ".[docling]"` or `pip install docling`. The helper lazy-imports Docling so missing packages only fail when `--docling` is used.

### Docling path = PDF → Markdown → `md_to_tree`

Not a drop-in replacement for `get_page_tokens` / PyPDF2. When `--docling` is set, the CLI converts with Docling, writes Markdown under `./workspace/{catalog}/{stem}.md`, then runs the existing markdown tree builder. Without `--docling`, the classic PDF / Flash paths are unchanged.

### Catalog required only with `--docling`

`--catalog` is optional for normal PDF/MD/Flash runs (outputs go to `./workspace/` or `./workspace/{catalog}/`). With `--docling` it is required because the extracted MD path is `./workspace/{catalog}/{filename}.md`.

### All CLI structure JSON under `./workspace/`

Previously outputs went to `./results/`. CLI now always writes `{stem}_structure.json` (or `_structure_flash`) under `./workspace/`, nested under `{catalog}/` when `--catalog` is set. This is a breaking change for anyone scripting against `./results/`.

### Catalog name sanitization

Catalog names must be a single path segment (no `/`, `\`, `.`, `..`, or absolute paths) so outputs cannot escape `./workspace/`.

### Mutual exclusion: `--docling` vs `--flash`

Flash is a PDF layout/heuristic pipeline; Docling routes through Markdown. Specifying both is an error.

### CLI-only scope

`PageIndexClient` and its `_meta.json` workspace layout were **not** changed. Catalog grouping is a CLI filesystem convention, not the client’s `doc_id` store.

## Tradeoffs

| Choice                              | Benefit                                          | Cost                                                                                    |
| ----------------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------- |
| Optional `[docling]` extra          | Light default install                            | Users must install Docling separately                                                   |
| MD intermediate via Docling         | Reuses `md_to_tree`; preserves Docling structure | Tree quality depends on Docling headings (`#` levels), not PDF page indices             |
| Flat `./workspace/` without catalog | Simple default                                   | Mixed with catalog folders; avoid naming a catalog after a file stem that would collide |

## Follow-ups (not done)

- Wire `--catalog` / Docling into `PageIndexClient.index()`
- Migrate or document legacy `./results/` consumers
- Tests for catalog validation and Docling branch (would need Docling or mocks)

---

# Implementation note: PageIndex FastMCP (CLI catalogs)

## Decisions

### Catalog workspaces, not `PageIndexClient`

MCP tools operate on `./workspace/{name}/` CLI catalogs (`*_structure.json` + companion sources). They do **not** use `PageIndexClient` UUID / `_meta.json` stores. Agents discover catalogs via `get_all_workspace`.

### `doc_id` = document stem

Within a workspace, `doc_id` is the filename stem without `_structure` / `_structure_flash` (e.g. matching on-disk names under `factset-street-accounts/`). Named catalogs are required for MCP insert (no flat root indexing in v1).

### Source always persisted on insert

`insert_page_index` copies/downloads/decodes the file into the catalog folder before indexing so `get_page_content` can read companion `.md` / `.pdf` later. Existing catalog docs that only have structure JSON and no source return an actionable error.

### MD page content prefers companion file

Many CLI structure trees omit node `text`. For Markdown, MCP slices the companion `.md` using `line_num` boundaries from the tree; falls back to node text / raw lines when needed.

### Insert inputs: path, URL, or base64

Exactly one of `file_path`, `url`, or `file_base64`. `filename` is required for base64.

### MCP PDF default = CLI Docling

PDF inserts use the same pipeline as `run_pageindex.py --docling --catalog …`: Docling converts to Markdown under the workspace, then `md_to_tree` writes `{stem}_structure.json`. The original PDF is also kept in the catalog. Retrieval treats the doc as Markdown (`line_num` / companion `.md`). Requires `pip install docling`. No Flash flag on MCP insert in v1.

### FastMCP via official MCP SDK

Uses `mcp.server.fastmcp.FastMCP` (same house pattern as yahoo-finance-mcp). Pin **`mcp>=1.27,<2`** because MCP SDK 2.x removed the FastMCP module. Transport: stdio default; `--http` for streamable HTTP. No HTTP auth in v1 — bind to localhost if exposing HTTP.

### Env

- `PAGEINDEX_WORKSPACE_ROOT` (default `./workspace`)
- `PAGEINDEX_MCP_HTTP_HOST` / `PORT` / `PATH` (defaults `127.0.0.1`, `8765`, `/mcp/page-index/v1`)

## Tradeoffs

| Choice                         | Benefit                                   | Cost                                                                          |
| ------------------------------ | ----------------------------------------- | ----------------------------------------------------------------------------- |
| CLI catalogs only              | Works with existing `workspace/` data     | Client `_meta.json` demos need separate tooling                               |
| Persist source on insert       | Reliable `get_page_content`               | Duplicates files already elsewhere on disk                                    |
| MCP PDF via Docling by default | Matches CLI `--docling` catalog artifacts | Docling required for PDF MCP inserts; no classic `page_index` PDF path in MCP |
| No Flash on MCP insert         | Smaller surface                           | Agents cannot trigger Flash via MCP yet                                       |
| No HTTP auth                   | Simple local Cursor setup                 | Do not expose `--http` on untrusted networks                                  |

### `pyproject.toml` restored

Package metadata matches `requirements.txt` / `uv.lock` (`pageindex==0.1.0`, Python `>=3.12`). Optional extras: `[docling]`, `[flash]`, `[agents]`, `[all]`. Console script: `pageindex-mcp`.

### Docker Compose + configurable config/env

- `PAGEINDEX_CONFIG_PATH` — YAML used by `ConfigLoader` (Compose mounts host `config.yaml` at `/config/config.yaml`).
- `PAGEINDEX_ENV_FILE` — optional dotenv path; Compose prefers `env_file: .env` injected into the container.
- **LAN / IP bind:** `PAGEINDEX_MCP_HTTP_HOST=0.0.0.0` (or `--http --host 0.0.0.0`) so clients use `http://<machine-ip>:8765/mcp/page-index/v1`. Default remains `127.0.0.1`. Compose already sets `0.0.0.0` in-container. No HTTP auth in v1 — firewall/VPN if exposing beyond localhost. DNS-rebinding protection stays off for non-localhost Host headers.

### MCP download / delete

- `download_document(workspace, doc_id)` returns the stored original as base64 (PDF preferred over Docling `.md`).
- `delete_document(workspace, doc_id)` removes `{stem}_structure.json` / `_structure_flash.json` and companion `.pdf`/`.md`/`.markdown` for that stem.

---

# Implementation note: MCP README + `reference/` reorg

## Decisions

### Root README is MCP-first

Replaced the Vectify marketing README with a guide for this fork’s FastMCP server (tools, install, Cursor, Docker, workspace model). Upstream content is not deleted.

### Upstream materials under `reference/`

Moved forked non-runtime materials only:

- Current README → `reference/upstream-README.md`
- `cookbook/` → `reference/cookbook/`
- `examples/` → `reference/examples/`
- Added `reference/README.md` as an index

Core package (`pageindex/`), CLI, Docker, and `workspace/` stay at the product root.

### Path fix-ups

Updated docstring/`__main__` sample paths in `pageindex/client.py` and `pageindex/page_index_md.py` to `reference/examples/...`. Updated `CONTEXT.md` Source docs table.
