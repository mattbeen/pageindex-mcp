"""Optional Docling PDF → Markdown conversion for the CLI."""

from __future__ import annotations

import os
from pathlib import Path


WORKSPACE_ROOT = Path("./workspace")


def validate_catalog_name(catalog: str) -> str:
    """Reject empty names and path separators so catalogs stay under ./workspace/."""
    if not catalog or not catalog.strip():
        raise ValueError("Catalog name must be a non-empty string")
    name = catalog.strip()
    if name in (".", "..") or "/" in name or "\\" in name or os.sep in name:
        raise ValueError(
            f"Invalid catalog name {catalog!r}: must not contain path separators "
            "or be '.' / '..'"
        )
    if Path(name).is_absolute() or Path(name).parts != (name,):
        raise ValueError(f"Invalid catalog name {catalog!r}: must be a single path segment")
    return name


def pdf_to_markdown(pdf_path: str) -> str:
    """Convert a PDF to Markdown via Docling. Lazy-imports so Docling is optional."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise ImportError(
            "Docling is required for --docling. Install with: pip install -e \".[docling]\" "
            "or: pip install docling"
        ) from e

    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    return result.document.export_to_markdown()


def save_markdown(md_text: str, catalog: str, pdf_path: str) -> Path:
    """Write extracted Markdown to ./workspace/{catalog}/{stem}.md."""
    catalog = validate_catalog_name(catalog)
    stem = Path(pdf_path).stem
    out_dir = WORKSPACE_ROOT / catalog
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.md"
    out_path.write_text(md_text, encoding="utf-8")
    return out_path
