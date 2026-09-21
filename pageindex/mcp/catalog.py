"""CLI catalog workspace adapter for the PageIndex MCP server.

Workspaces live under ``PAGEINDEX_WORKSPACE_ROOT`` (default ``./workspace``) as
``{workspace}/{doc_id}_structure.json`` plus optional companion source files.
This is separate from ``PageIndexClient`` ``_meta.json`` stores.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import json
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
import PyPDF2

from pageindex.docling_convert import pdf_to_markdown, validate_catalog_name
from pageindex.page_index_md import md_to_tree
from pageindex.retrieve import (
    _get_md_page_content,
    _get_pdf_page_content,
    _parse_pages,
)
from pageindex.utils import ConfigLoader, remove_fields

DESC_CAP = 240
STRUCTURE_SUFFIX = "_structure"
STRUCTURE_FLASH_SUFFIX = "_structure_flash"
SOURCE_EXTENSIONS = (".md", ".markdown", ".pdf")
# Prefer uploaded original (PDF) over Docling markdown when downloading.
ORIGINAL_EXTENSIONS = (".pdf", ".md", ".markdown")
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


def workspace_root() -> Path:
    raw = os.getenv("PAGEINDEX_WORKSPACE_ROOT", "./workspace")
    return Path(raw).expanduser().resolve()


def _workspace_dir(workspace: str) -> Path:
    name = validate_catalog_name(workspace)
    return workspace_root() / name


def _error(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


def _ok(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _read_json(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _stem_from_structure_name(filename: str) -> str | None:
    name = filename
    if name.endswith(".json"):
        name = name[:-5]
    if name.endswith(STRUCTURE_FLASH_SUFFIX):
        return name[: -len(STRUCTURE_FLASH_SUFFIX)]
    if name.endswith(STRUCTURE_SUFFIX):
        return name[: -len(STRUCTURE_SUFFIX)]
    return None


def _structure_path(ws_dir: Path, doc_id: str) -> Path | None:
    primary = ws_dir / f"{doc_id}{STRUCTURE_SUFFIX}.json"
    if primary.is_file():
        return primary
    flash = ws_dir / f"{doc_id}{STRUCTURE_FLASH_SUFFIX}.json"
    if flash.is_file():
        return flash
    return None


def _list_structure_files(ws_dir: Path) -> list[Path]:
    if not ws_dir.is_dir():
        return []
    files = []
    for path in ws_dir.iterdir():
        if not path.is_file() or not path.name.endswith(".json"):
            continue
        if _stem_from_structure_name(path.name) is not None:
            files.append(path)
    return sorted(files)


def _companion_source(ws_dir: Path, doc_id: str) -> Path | None:
    for ext in SOURCE_EXTENSIONS:
        candidate = ws_dir / f"{doc_id}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _original_source(ws_dir: Path, doc_id: str) -> Path | None:
    """Prefer the uploaded original (PDF), then markdown companions."""
    for ext in ORIGINAL_EXTENSIONS:
        candidate = ws_dir / f"{doc_id}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _related_artifact_paths(ws_dir: Path, doc_id: str) -> list[Path]:
    """All on-disk artifacts for an indexed doc (structure + sources)."""
    names = [
        f"{doc_id}{STRUCTURE_SUFFIX}.json",
        f"{doc_id}{STRUCTURE_FLASH_SUFFIX}.json",
        *[f"{doc_id}{ext}" for ext in SOURCE_EXTENSIONS],
    ]
    paths = []
    for name in names:
        path = ws_dir / name
        if path.is_file():
            paths.append(path)
    return paths


def _ensure_under_workspace(path: Path, ws_dir: Path) -> Path:
    resolved = path.resolve()
    root = ws_dir.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as e:
        raise ValueError(f"Path escapes workspace directory: {resolved}") from e
    return resolved


def _has_field_in_tree(nodes: Any, field: str) -> bool:
    if not isinstance(nodes, list):
        return False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if field in node and node[field] is not None:
            return True
        if _has_field_in_tree(node.get("nodes"), field):
            return True
    return False


def _infer_doc_type(data: dict, source: Path | None) -> str:
    if source is not None:
        ext = source.suffix.lower()
        if ext == ".pdf":
            return "pdf"
        if ext in (".md", ".markdown"):
            return "md"
    structure = data.get("structure", [])
    if _has_field_in_tree(structure, "line_num"):
        return "md"
    if _has_field_in_tree(structure, "physical_index") or _has_field_in_tree(
        structure, "start_index"
    ):
        return "pdf"
    if data.get("line_count") is not None:
        return "md"
    if data.get("page_count") is not None:
        return "pdf"
    return "md"


def _truncate(text: str, limit: int = DESC_CAP) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _pdf_page_count(source: Path | None, data: dict) -> int | None:
    if data.get("page_count") is not None:
        return int(data["page_count"])
    if source and source.suffix.lower() == ".pdf":
        try:
            with open(source, "rb") as f:
                return len(PyPDF2.PdfReader(f).pages)
        except Exception:
            return None
    return None


def _doc_meta_from_structure(doc_id: str, path: Path) -> dict:
    data = _read_json(path) or {}
    source = _companion_source(path.parent, doc_id)
    doc_type = _infer_doc_type(data, source)
    meta = {
        "doc_id": doc_id,
        "doc_name": data.get("doc_name") or doc_id,
        "doc_description": _truncate(str(data.get("doc_description", ""))),
        "type": doc_type,
    }
    return meta


def list_workspaces() -> str:
    root = workspace_root()
    if not root.is_dir():
        return _ok([])

    workspaces = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            validate_catalog_name(child.name)
        except ValueError:
            continue
        structures = _list_structure_files(child)
        if not structures:
            continue
        documents = []
        for struct_path in structures:
            stem = _stem_from_structure_name(struct_path.name)
            if not stem:
                continue
            documents.append(_doc_meta_from_structure(stem, struct_path))
        workspaces.append(
            {
                "name": child.name,
                "doc_count": len(documents),
                "documents": documents,
            }
        )
    return _ok(workspaces)


def _load_doc(workspace: str, doc_id: str) -> tuple[Path, dict, Path | None] | str:
    """Return (structure_path, data, source) or an error JSON string."""
    try:
        ws_dir = _workspace_dir(workspace)
    except ValueError as e:
        return _error(str(e))
    struct_path = _structure_path(ws_dir, doc_id)
    if not struct_path:
        return _error(
            f"Document {doc_id!r} not found in workspace {workspace!r}. "
            f"Expected {doc_id}_structure.json under {ws_dir}."
        )
    data = _read_json(struct_path)
    if data is None:
        return _error(f"Failed to read structure JSON: {struct_path}")
    source = _companion_source(ws_dir, doc_id)
    return struct_path, data, source


def get_document(workspace: str, doc_id: str) -> str:
    loaded = _load_doc(workspace, doc_id)
    if isinstance(loaded, str):
        return loaded
    _, data, source = loaded
    doc_type = _infer_doc_type(data, source)
    result: dict[str, Any] = {
        "doc_id": doc_id,
        "doc_name": data.get("doc_name") or doc_id,
        "doc_description": data.get("doc_description", ""),
        "type": doc_type,
        "status": "completed",
        "workspace": workspace,
    }
    if doc_type == "pdf":
        count = _pdf_page_count(source, data)
        result["page_count"] = count if count is not None else 0
    else:
        if data.get("line_count") is not None:
            result["line_count"] = data["line_count"]
        elif source and source.suffix.lower() in (".md", ".markdown"):
            text = source.read_text(encoding="utf-8")
            result["line_count"] = text.count("\n") + (1 if text else 0)
        else:
            result["line_count"] = 0
    return _ok(result)


def get_document_structure(workspace: str, doc_id: str) -> str:
    loaded = _load_doc(workspace, doc_id)
    if isinstance(loaded, str):
        return loaded
    _, data, _ = loaded
    structure = data.get("structure", [])
    return _ok(remove_fields(structure, fields=["text"]))


def _collect_line_nums(nodes: list, out: list[int]) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ln = node.get("line_num")
        if isinstance(ln, int):
            out.append(ln)
        if node.get("nodes"):
            _collect_line_nums(node["nodes"], out)


def _md_content_from_file(source: Path, structure: list, page_nums: list[int]) -> list[dict]:
    """Slice companion markdown using structure line_num boundaries."""
    lines = source.read_text(encoding="utf-8").splitlines()
    all_headers: list[int] = []
    _collect_line_nums(structure, all_headers)
    all_headers = sorted(set(all_headers))
    min_line, max_line = min(page_nums), max(page_nums)
    targets = [ln for ln in all_headers if min_line <= ln <= max_line]
    if not targets:
        # Raw line fallback when no header nodes fall in range
        results = []
        for ln in page_nums:
            if 1 <= ln <= len(lines):
                results.append({"page": ln, "content": lines[ln - 1]})
        return results

    results = []
    for ln in targets:
        # line_num is 1-indexed
        start = ln - 1
        next_headers = [h for h in all_headers if h > ln]
        end = (next_headers[0] - 1) if next_headers else len(lines)
        chunk = "\n".join(lines[start:end]).strip()
        results.append({"page": ln, "content": chunk})
    return results


def get_page_content(workspace: str, doc_id: str, pages: str) -> str:
    loaded = _load_doc(workspace, doc_id)
    if isinstance(loaded, str):
        return loaded
    _, data, source = loaded
    doc_type = _infer_doc_type(data, source)

    try:
        page_nums = _parse_pages(pages)
    except (ValueError, AttributeError) as e:
        return _error(
            f'Invalid pages format: {pages!r}. Use "5-7", "3,8", or "12". Error: {e}'
        )

    try:
        if doc_type == "pdf":
            doc_info = {
                "type": "pdf",
                "path": str(source) if source else "",
                "structure": data.get("structure", []),
                "page_count": data.get("page_count"),
            }
            if source and source.suffix.lower() == ".pdf":
                content = _get_pdf_page_content(doc_info, page_nums)
            else:
                # Fall back to node text embedded in structure
                structure = data.get("structure", [])
                content = []
                page_set = set(page_nums)

                def _walk(nodes):
                    for node in nodes or []:
                        if not isinstance(node, dict):
                            continue
                        for key in ("physical_index", "start_index"):
                            idx = node.get(key)
                            if idx in page_set and node.get("text"):
                                content.append({"page": idx, "content": node["text"]})
                                break
                        _walk(node.get("nodes"))

                _walk(structure)
                content.sort(key=lambda x: x["page"])
                if not content:
                    return _error(
                        f"No PDF source found for {doc_id!r} in workspace {workspace!r} "
                        "and structure nodes have no text. Re-run insert_page_index with "
                        "the original PDF (path, url, or file_base64)."
                    )
        else:
            structure = data.get("structure", [])
            if source and source.suffix.lower() in (".md", ".markdown"):
                content = _md_content_from_file(source, structure, page_nums)
            else:
                doc_info = {"type": "md", "structure": structure}
                content = _get_md_page_content(doc_info, page_nums)
                if not content or all(not c.get("content") for c in content):
                    return _error(
                        f"No Markdown source found for {doc_id!r} in workspace "
                        f"{workspace!r} and structure nodes have no text. "
                        "Re-run insert_page_index with the original file."
                    )
    except Exception as e:
        return _error(f"Failed to read page content: {e}")

    return _ok(content)


def _filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if not name:
        raise ValueError(f"Could not derive filename from URL: {url}")
    return name


def _resolve_mode(filename: str, mode: str) -> str:
    mode = (mode or "auto").lower()
    if mode not in ("auto", "pdf", "md"):
        raise ValueError(f"Invalid mode {mode!r}: use auto, pdf, or md")
    ext = Path(filename).suffix.lower()
    if mode == "auto":
        if ext == ".pdf":
            return "pdf"
        if ext in (".md", ".markdown"):
            return "md"
        raise ValueError(
            f"Unsupported file format for {filename!r}. Use .pdf, .md, or .markdown, "
            "or set mode explicitly."
        )
    if mode == "pdf" and ext and ext != ".pdf":
        raise ValueError(f"mode=pdf requires a .pdf file, got {filename!r}")
    if mode == "md" and ext and ext not in (".md", ".markdown"):
        raise ValueError(f"mode=md requires a .md/.markdown file, got {filename!r}")
    return mode


def _materialize_source(
    ws_dir: Path,
    *,
    file_path: str | None,
    url: str | None,
    file_base64: str | None,
    filename: str | None,
) -> Path:
    provided = [x for x in (file_path, url, file_base64) if x]
    if len(provided) != 1:
        raise ValueError(
            "Provide exactly one of file_path, url, or file_base64."
        )

    if file_path:
        src = Path(file_path).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"File not found: {src}")
        dest_name = filename or src.name
        dest = ws_dir / dest_name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        return dest

    if url:
        dest_name = filename or _filename_from_url(url)
        dest = ws_dir / dest_name
        with httpx.Client(follow_redirects=True, timeout=120.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return dest

    # file_base64
    if not filename:
        raise ValueError("filename is required when using file_base64")
    dest = ws_dir / filename
    raw = file_base64.strip()
    # Allow data URL prefix
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        dest.write_bytes(base64.b64decode(raw, validate=False))
    except Exception as e:
        raise ValueError(f"Invalid base64 content: {e}") from e
    return dest


def _run_async(coro):
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


def _md_to_tree_result(md_path: Path) -> dict:
    opt = ConfigLoader().load(None)
    coro = md_to_tree(
        md_path=str(md_path),
        if_thinning=False,
        if_add_node_summary=opt.if_add_node_summary,
        summary_token_threshold=200,
        model=opt.model,
        if_add_doc_description=opt.if_add_doc_description,
        if_add_node_text=opt.if_add_node_text,
        if_add_node_id=opt.if_add_node_id,
    )
    return _run_async(coro)


def _index_pdf_via_docling(pdf_path: Path, ws_dir: Path) -> dict:
    """Match CLI ``--docling``: PDF → Markdown → ``md_to_tree``."""
    try:
        md_text = pdf_to_markdown(str(pdf_path))
    except ImportError as e:
        raise ImportError(
            "Docling is required for MCP PDF indexing (same as CLI --docling). "
            "Install with: pip install docling"
        ) from e

    md_path = ws_dir / f"{pdf_path.stem}.md"
    md_path.write_text(md_text, encoding="utf-8")
    result = _md_to_tree_result(md_path)
    out = dict(result) if isinstance(result, dict) else {
        "doc_name": pdf_path.stem,
        "structure": result,
    }
    out.setdefault("doc_name", pdf_path.stem)
    out["markdown_path"] = str(md_path)
    out["pipeline"] = "docling"
    return out


def _index_file(path: Path, mode: str, ws_dir: Path) -> dict:
    if mode == "pdf":
        return _index_pdf_via_docling(path, ws_dir)
    return _md_to_tree_result(path)


def _save_structure(ws_dir: Path, stem: str, data: dict) -> Path:
    out = ws_dir / f"{stem}{STRUCTURE_SUFFIX}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out


def insert_page_index(
    workspace: str,
    file_path: str | None = None,
    url: str | None = None,
    file_base64: str | None = None,
    filename: str | None = None,
    mode: str = "auto",
) -> str:
    try:
        name = validate_catalog_name(workspace)
        ws_dir = workspace_root() / name
        ws_dir.mkdir(parents=True, exist_ok=True)

        dest = _materialize_source(
            ws_dir,
            file_path=file_path,
            url=url,
            file_base64=file_base64,
            filename=filename,
        )
        resolved_mode = _resolve_mode(dest.name, mode)
        indexed = _index_file(dest, resolved_mode, ws_dir)

        # After Docling, artifacts are Markdown-shaped (line_count / line_num).
        effective_type = "md" if resolved_mode == "pdf" else resolved_mode

        save_payload = {
            "doc_name": indexed.get("doc_name", dest.stem),
            "structure": indexed.get("structure", []),
        }
        if indexed.get("doc_description") is not None:
            save_payload["doc_description"] = indexed["doc_description"]
        if effective_type == "md":
            save_payload["line_count"] = indexed.get("line_count")
        else:
            save_payload["page_count"] = indexed.get("page_count")

        structure_path = _save_structure(ws_dir, dest.stem, save_payload)
        result = {
            "workspace": name,
            "doc_id": dest.stem,
            "doc_name": save_payload["doc_name"],
            "type": effective_type,
            "structure_path": str(structure_path),
            "source_path": str(dest),
        }
        if resolved_mode == "pdf":
            result["pipeline"] = indexed.get("pipeline", "docling")
            if indexed.get("markdown_path"):
                result["markdown_path"] = indexed["markdown_path"]
        if effective_type == "md":
            result["line_count"] = save_payload.get("line_count")
        else:
            result["page_count"] = save_payload.get("page_count")
        return _ok(result)
    except Exception as e:
        return _error(str(e))


def download_document(workspace: str, doc_id: str) -> str:
    """Return the original stored source file as base64 (PDF preferred over MD)."""
    try:
        ws_dir = _workspace_dir(workspace)
    except ValueError as e:
        return _error(str(e))
    if not ws_dir.is_dir():
        return _error(f"Workspace {workspace!r} not found under {workspace_root()}.")

    source = _original_source(ws_dir, doc_id)
    if source is None:
        related = _related_artifact_paths(ws_dir, doc_id)
        if not related and _structure_path(ws_dir, doc_id) is None:
            return _error(
                f"Document {doc_id!r} not found in workspace {workspace!r}."
            )
        return _error(
            f"No original source file (.pdf/.md) found for {doc_id!r} in "
            f"workspace {workspace!r}. Re-insert with the source file."
        )

    try:
        path = _ensure_under_workspace(source, ws_dir)
        data = path.read_bytes()
    except Exception as e:
        return _error(f"Failed to read source file: {e}")

    ext = path.suffix.lower()
    return _ok(
        {
            "workspace": workspace,
            "doc_id": doc_id,
            "filename": path.name,
            "media_type": MEDIA_TYPES.get(ext, "application/octet-stream"),
            "size_bytes": len(data),
            "encoding": "base64",
            "content_base64": base64.b64encode(data).decode("ascii"),
            "source_path": str(path),
        }
    )


def delete_document(workspace: str, doc_id: str) -> str:
    """Delete structure JSON and companion source files for a document stem."""
    try:
        name = validate_catalog_name(workspace)
        ws_dir = workspace_root() / name
    except ValueError as e:
        return _error(str(e))
    if not ws_dir.is_dir():
        return _error(f"Workspace {workspace!r} not found under {workspace_root()}.")

    # Accept doc_name with extension by normalizing to stem
    doc_key = Path(doc_id).stem if Path(doc_id).suffix.lower() in SOURCE_EXTENSIONS else doc_id
    # Also strip accidental _structure suffix from callers
    if doc_key.endswith(STRUCTURE_FLASH_SUFFIX):
        doc_key = doc_key[: -len(STRUCTURE_FLASH_SUFFIX)]
    elif doc_key.endswith(STRUCTURE_SUFFIX):
        doc_key = doc_key[: -len(STRUCTURE_SUFFIX)]

    related = _related_artifact_paths(ws_dir, doc_key)
    if not related:
        return _error(
            f"No indexed artifacts found for {doc_id!r} in workspace {workspace!r}."
        )

    deleted: list[str] = []
    errors: list[str] = []
    for path in related:
        try:
            safe = _ensure_under_workspace(path, ws_dir)
            safe.unlink()
            deleted.append(str(safe))
        except Exception as e:
            errors.append(f"{path.name}: {e}")

    payload: dict[str, Any] = {
        "workspace": name,
        "doc_id": doc_key,
        "deleted": deleted,
        "deleted_count": len(deleted),
    }
    if errors:
        payload["errors"] = errors
        if not deleted:
            return _error(f"Failed to delete {doc_id!r}: {'; '.join(errors)}")
    return _ok(payload)
