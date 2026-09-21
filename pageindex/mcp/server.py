"""FastMCP server and tool registration for PageIndex CLI catalogs."""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from pageindex.mcp import catalog

mcp = FastMCP("pageindex", streamable_http_path="/mcp/page-index/v1")


@mcp.tool()
async def get_all_workspace() -> str:
    """Get all existing workspaces (catalog folders) under the PageIndex workspace root.

    Returns each workspace name, document count, and a short list of documents
    (doc_id, doc_name, doc_description, type) so you can pick the catalog most
    relevant to a query.
    """
    return await asyncio.to_thread(catalog.list_workspaces)


@mcp.tool()
async def get_document(workspace: str, doc_id: str) -> str:
    """Get document metadata: status, page/line count, name, and description.

    Args:
        workspace: Catalog name under the workspace root (e.g. factset-street-accounts).
        doc_id: Document stem (filename without _structure.json).
    """
    return await asyncio.to_thread(catalog.get_document, workspace, doc_id)


@mcp.tool()
async def get_document_structure(workspace: str, doc_id: str) -> str:
    """Get the document's full tree structure (without text) to find relevant sections.

    Args:
        workspace: Catalog name under the workspace root.
        doc_id: Document stem (filename without _structure.json).
    """
    return await asyncio.to_thread(catalog.get_document_structure, workspace, doc_id)


@mcp.tool()
async def get_page_content(workspace: str, doc_id: str, pages: str) -> str:
    """Get the text content of specific pages or line numbers.

    Use tight ranges: e.g. '5-7' for pages 5 to 7, '3,8' for pages 3 and 8,
    '12' for page 12. For Markdown documents, use line numbers from the
    structure's line_num field.

    Args:
        workspace: Catalog name under the workspace root.
        doc_id: Document stem (filename without _structure.json).
        pages: Page/line selector such as '5-7', '3,8', or '12'.
    """
    return await asyncio.to_thread(catalog.get_page_content, workspace, doc_id, pages)


@mcp.tool()
async def insert_page_index(
    workspace: str,
    file_path: str | None = None,
    url: str | None = None,
    file_base64: str | None = None,
    filename: str | None = None,
    mode: str = "auto",
) -> str:
    """Upload and index a document into an existing or new workspace (catalog).

    Provide exactly one of file_path, url, or file_base64. When using file_base64,
    filename is required. The source file is stored under the workspace folder.

    PDF files use the same pipeline as CLI ``--docling``: Docling converts PDF to
    Markdown, then ``md_to_tree`` builds ``{stem}.md`` + ``{stem}_structure.json``.
    Markdown files are indexed with ``md_to_tree`` directly. Requires Docling for PDFs
    (``pip install docling``).

    Args:
        workspace: Existing or new catalog name under the workspace root.
        file_path: Absolute or relative path on the MCP host filesystem.
        url: HTTP(S) URL to download and index.
        file_base64: Base64-encoded file bytes (optional data: URL prefix allowed).
        filename: Destination filename; required for file_base64; optional for url.
        mode: auto, pdf, or md (default auto from extension).
    """
    return await asyncio.to_thread(
        catalog.insert_page_index,
        workspace,
        file_path,
        url,
        file_base64,
        filename,
        mode,
    )


@mcp.tool()
async def download_document(workspace: str, doc_id: str) -> str:
    """Download the original document stored in a workspace catalog.

    Prefers the uploaded PDF when both PDF and Docling Markdown exist.
    Returns JSON with filename, media_type, size_bytes, and content_base64.

    Args:
        workspace: Catalog name under the workspace root.
        doc_id: Document stem (same id used by get_document / insert_page_index).
    """
    return await asyncio.to_thread(catalog.download_document, workspace, doc_id)


@mcp.tool()
async def delete_document(workspace: str, doc_id: str) -> str:
    """Delete all indexed artifacts for a document in a workspace.

    Removes ``{doc_id}_structure.json`` (and flash variant if present) plus
    companion ``.pdf`` / ``.md`` / ``.markdown`` files with the same stem.

    Args:
        workspace: Catalog name under the workspace root.
        doc_id: Document stem or filename (extension optional), e.g. doc name
            from get_all_workspace / insert_page_index.
    """
    return await asyncio.to_thread(catalog.delete_document, workspace, doc_id)
