# Context: PageIndex (local CLI extensions)

High-signal domain and architecture context for **this repository**, including local CLI extensions for **Docling** conversion and **multi-catalog** workspace layout.

**Audience:** humans and coding agents.  
**Keep current:** update glossary, contracts, and invariants when semantics change.

## How agents should use this file

1. Skim **System map** and **Invariants** before editing unfamiliar CLI/output code.
2. For behavior changes, trace the relevant **Core workflow** end to end.
3. Before changing outputs or CLI flags, check **Public contracts** and **Glossary**.
4. For depth, follow **Source docs** — do not duplicate them here.

**Out of scope for this file:** coding standards, lint rules, commit conventions, transient debugging detail (see `implementation-note.md`).

---

## Scope

**Covers**

- Self-hosted PageIndex tree generation (PDF, Markdown, Flash)
- Optional Docling PDF→Markdown path via CLI
- Multi-catalog output under `./workspace/`
- Library entry points (`page_index`, `md_to_tree`, `PageIndexClient`) as they relate to CLI

**Does not duplicate**

- Low-level coding standards
- Full Flash pipeline internals
- Cloud PageIndex API / File System product docs

---

## System map

| Part                           | Owns                                                     | Must not own        | Key interactions                                                                                            |
| ------------------------------ | -------------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------- |
| `run_pageindex.py`             | CLI flags, validation, output paths under `./workspace/` | Docling API details | Calls `page_index_main`, Flash, Docling helper, `md_to_tree`                                                |
| `pageindex/docling_convert.py` | Lazy Docling convert + MD save + catalog name validation | Tree building       | CLI `--docling` and MCP PDF insert                                                                          |
| `pageindex/page_index.py`      | LLM PDF tree (PyPDF2 pages)                              | Catalog folders     | Default `--pdf_path` path                                                                                   |
| `pageindex/page_index_md.py`   | Markdown heading tree                                    | PDF extraction      | `--md_path` and Docling path                                                                                |
| `pageindex/flash/`             | Heuristic PDF TOC (no LLM for structure)                 | Docling / catalogs  | `--flash`                                                                                                   |
| `pageindex/client.py`          | In-memory / `_meta.json` workspace by `doc_id`           | CLI catalog folders | Separate from CLI `./workspace/{catalog}/`                                                                  |
| `pageindex/mcp/`               | FastMCP tools over CLI catalogs under `./workspace/`     | Client `_meta.json` | Lists/indexes/reads `{catalog}/*_structure.json` + sources; PDF insert uses Docling→MD like CLI `--docling` |

### Ownership boundaries

- **CLI** owns where files land on disk (`./workspace/`, catalogs).
- **Docling helper** owns conversion and MD persistence; tree logic stays in `md_to_tree`. Used by CLI `--docling` and MCP PDF insert.
- **`PageIndexClient`** owns its own workspace JSON store; it does **not** implement `--catalog` / `--docling`.
- **MCP** (`pageindex/mcp`) reads/writes the same CLI catalog layout; PDF insert uses Docling by default; it does **not** use `PageIndexClient` `_meta.json`.

### Entry points

- **CLI:** `python run_pageindex.py --pdf_path …` / `--md_path …`
- **Library:** `page_index()`, `md_to_tree()`, `page_index_flash()`, `PageIndexClient.index()`
- **MCP:** `python -m pageindex.mcp` (stdio) or `python -m pageindex.mcp --http` (`PAGEINDEX_MCP_HTTP_HOST=0.0.0.0` / `--host 0.0.0.0` for LAN IP access; default `127.0.0.1`)

---

## Core workflows

### Default PDF index (PyPDF2)

| Step             | What happens                                                             |
| ---------------- | ------------------------------------------------------------------------ |
| 1. Trigger       | `--pdf_path` without `--docling` / `--flash`                             |
| 2. Orchestration | `page_index_main` → `get_page_tokens` (PyPDF2) → LLM tree                |
| 3. Side effects  | Write `./workspace/{stem}_structure.json` (or under `{catalog}/` if set) |
| 4. Done          | Print saved path                                                         |

### Docling + catalog index

| Step             | What happens                                                |
| ---------------- | ----------------------------------------------------------- |
| 1. Trigger       | `--pdf_path --docling --catalog <name>`                     |
| 2. Orchestration | Docling `DocumentConverter` → Markdown → `md_to_tree`       |
| 3. Side effects  | `./workspace/{catalog}/{stem}.md` + `{stem}_structure.json` |
| 4. Done          | Print MD and JSON paths                                     |

**Branches:** `--docling` without `--catalog` or with `--flash` → error. Missing Docling package → ImportError with install hint.

### Catalog-only grouping

| Step       | What happens                                                                 |
| ---------- | ---------------------------------------------------------------------------- |
| 1. Trigger | Any index path with `--catalog` (no Docling required)                        |
| 2. Done    | Structure JSON under `./workspace/{catalog}/` instead of flat `./workspace/` |

---

## Public contracts

### CLI

- **Surface:** `run_pageindex.py`
- **Flags:** `--pdf_path` \| `--md_path`; optional `--flash`, `--docling`, `--catalog`, model/node options
- **Success paths:**
  - No catalog: `./workspace/{stem}_structure.json` (or `_structure_flash`)
  - With catalog: `./workspace/{catalog}/{stem}_structure.json`
  - Docling: also `./workspace/{catalog}/{stem}.md`
- **Install for Docling:** `pip install -e ".[docling]"` or `pip install docling`

### Contract rules

- Default PDF extractor remains PyPDF2 unless `--docling` or `--flash`.
- Catalog names are single path segments under `./workspace/`.
- Do not resurrect `./results/` as the CLI default without updating this file.

---

## Integrations

| Integration      | Provides       | On failure                  | Local seam                     |
| ---------------- | -------------- | --------------------------- | ------------------------------ |
| Docling          | PDF→Markdown   | ImportError / convert error | `pageindex/docling_convert.py` |
| LiteLLM / OpenAI | Tree LLM calls | Retries in utils            | `config.yaml` / `--model`      |
| PyPDF2 / PyMuPDF | Page text      | Parser errors               | `get_page_tokens`              |

---

## Glossary

| Term            | Meaning here                                           | Not to confuse with                               |
| --------------- | ------------------------------------------------------ | ------------------------------------------------- |
| Catalog         | Named collection folder under `./workspace/{catalog}/` | PageIndex cloud folders / File System             |
| Docling path    | CLI `--docling` or MCP PDF insert: PDF→MD→`md_to_tree` | Replacing `get_page_tokens`                       |
| Workspace (CLI) | `./workspace/` output root for CLI artifacts           | `PageIndexClient(workspace=…)` `_meta.json` store |
| Workspace (MCP) | Same as CLI catalog name under workspace root          | Client UUID / `_meta.json` workspace              |
| doc_id (MCP)    | Document stem (`{stem}_structure.json` without suffix) | Client UUID `doc_id`                              |
| Structure JSON  | Tree index written by the CLI                          | Raw Docling JSON export                           |

---

## Invariants

- Docling runs when CLI `--docling` is set, or when MCP indexes a PDF (MCP PDF default).
- `--docling` requires `--pdf_path` and `--catalog`; cannot combine with `--flash`.
- Catalog names cannot contain path separators or escape `./workspace/`.
- CLI structure JSON always lands under `./workspace/` (never `./results/` as of this extension).
- Docling stays an optional dependency for the default CLI install; MCP PDF insert requires Docling.
- MCP tools operate on named CLI catalogs only (v1); they do not bridge client `_meta.json` workspaces.
- MCP `insert_page_index` always persists the source file into the catalog folder alongside structure JSON.
- MCP PDF insert defaults to the CLI Docling path (PDF → Markdown → `md_to_tree`); Docling must be installed for PDF uploads.
- Runtime LLM settings come from `PAGEINDEX_CONFIG_PATH` when set (else packaged `pageindex/config.yaml`); secrets from process env / `.env`.

---

## Non-goals

- Cloud upload API or PageIndex File System in this repo
- Changing `PageIndexClient` meta layout for catalogs
- Using Docling as an alternate `pdf_parser` inside `get_page_tokens`
- MCP Flash flags on insert or HTTP auth in v1
- MCP PDF path using classic PyPDF2 `page_index` (MCP PDFs use Docling by default)

## Common pitfalls

- Expecting Docling output without installing the `[docling]` extra
- Passing `--docling` without `--catalog`
- Assuming `PageIndexClient` reads CLI catalog folders
- Assuming MCP tools read `PageIndexClient` `_meta.json` workspaces
- Naming a catalog the same as a file stem when using flat `./workspace/` (collision risk)

---

## Change guidance

1. Start from `run_pageindex.py` or `pageindex/docling_convert.py` for CLI/output changes.
2. Preserve extractor defaults and optional Docling install.
3. If semantics change, update **Glossary**, **Contracts**, and **Invariants** here and log decisions in `implementation-note.md`.

---

## Source docs

| Doc                                                   | Explains                                    |
| ----------------------------------------------------- | ------------------------------------------- |
| `./README.md`                                         | MCP install, tools, Cursor, Docker          |
| `./CONTEXT.md`                                        | Domain map, contracts, invariants           |
| `./implementation-note.md`                            | Decisions and tradeoffs for this extension  |
| `./pageindex/mcp/`                                    | Local FastMCP server over CLI catalogs      |
| `./pageindex/flash/README.md`                         | Flash pipeline                              |
| `./reference/`                                        | Upstream VectifyAI README, cookbooks, demos |
| [Docling](https://github.com/docling-project/docling) | Upstream converter                          |
