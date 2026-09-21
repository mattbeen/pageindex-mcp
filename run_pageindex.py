import argparse
import asyncio
import json
import os
from pathlib import Path

from pageindex import *
from pageindex.docling_convert import pdf_to_markdown, save_markdown, validate_catalog_name
from pageindex.page_index_md import md_to_tree
from pageindex.utils import ConfigLoader

WORKSPACE_ROOT = Path("./workspace")


def _resolve_output_dir(catalog: str | None) -> Path:
    if catalog:
        catalog = validate_catalog_name(catalog)
        return WORKSPACE_ROOT / catalog
    return WORKSPACE_ROOT


def _save_structure(data, stem: str, catalog: str | None, flash: bool = False) -> Path:
    output_dir = _resolve_output_dir(catalog)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_structure_flash" if flash else "_structure"
    output_file = output_dir / f"{stem}{suffix}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return output_file


def _run_md_to_tree(md_path: str, args, opt) -> dict:
    return asyncio.run(md_to_tree(
        md_path=md_path,
        if_thinning=args.if_thinning.lower() == "yes",
        min_token_threshold=args.thinning_threshold,
        if_add_node_summary=opt.if_add_node_summary,
        summary_token_threshold=args.summary_token_threshold,
        model=opt.model,
        if_add_doc_description=opt.if_add_doc_description,
        if_add_node_text=opt.if_add_node_text,
        if_add_node_id=opt.if_add_node_id,
    ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process PDF or Markdown document and generate structure")
    parser.add_argument("--pdf_path", type=str, help="Path to the PDF file")
    parser.add_argument("--md_path", type=str, help="Path to the Markdown file")
    parser.add_argument("--flash", action="store_true", help="Use PageIndex Flash (with --pdf_path)")
    parser.add_argument(
        "--docling",
        action="store_true",
        help="Convert PDF to Markdown via Docling, then build tree (requires --catalog)",
    )
    parser.add_argument(
        "--catalog",
        type=str,
        default=None,
        help="Catalog/collection name under ./workspace/{catalog}/ (required with --docling)",
    )

    parser.add_argument("--model", type=str, default=None, help="Model to use (overrides config.yaml)")

    parser.add_argument("--toc-check-pages", type=int, default=None,
                      help="Number of pages to check for table of contents (PDF only)")
    parser.add_argument("--max-pages-per-node", type=int, default=None,
                      help="Maximum number of pages per node (PDF only)")
    parser.add_argument("--max-tokens-per-node", type=int, default=None,
                      help="Maximum number of tokens per node (PDF only)")

    parser.add_argument("--if-add-node-id", type=str, default=None,
                      help="Whether to add node id to the node")
    parser.add_argument("--if-add-node-summary", type=str, default=None,
                      help="Whether to add summary to the node")
    parser.add_argument("--if-add-doc-description", type=str, default=None,
                      help="Whether to add doc description to the doc")
    parser.add_argument("--if-add-node-text", type=str, default=None,
                      help="Whether to add text to the node")

    # Markdown specific arguments
    parser.add_argument("--if-thinning", type=str, default="no",
                      help="Whether to apply tree thinning for markdown (markdown only)")
    parser.add_argument("--thinning-threshold", type=int, default=5000,
                      help="Minimum token threshold for thinning (markdown only)")
    parser.add_argument("--summary-token-threshold", type=int, default=200,
                      help="Token threshold for generating summaries (markdown only)")
    args = parser.parse_args()

    if not args.pdf_path and not args.md_path:
        raise ValueError("Either --pdf_path or --md_path must be specified")
    if args.pdf_path and args.md_path:
        raise ValueError("Only one of --pdf_path or --md_path can be specified")
    if args.docling and args.flash:
        raise ValueError("Only one of --docling or --flash can be specified")
    if args.docling and not args.pdf_path:
        raise ValueError("--docling requires --pdf_path")
    if args.docling and not args.catalog:
        raise ValueError("--docling requires --catalog")
    if args.catalog:
        validate_catalog_name(args.catalog)

    if args.pdf_path:
        if not args.pdf_path.lower().endswith(".pdf"):
            raise ValueError("PDF file must have .pdf extension")
        if not os.path.isfile(args.pdf_path):
            raise ValueError(f"PDF file not found: {args.pdf_path}")

        pdf_name = os.path.splitext(os.path.basename(args.pdf_path))[0]

        if args.docling:
            print("Converting PDF with Docling...")
            md_text = pdf_to_markdown(args.pdf_path)
            md_path = save_markdown(md_text, args.catalog, args.pdf_path)
            print(f"Markdown saved to: {md_path}")

            config_loader = ConfigLoader()
            user_opt = {
                "model": args.model,
                "if_add_node_summary": args.if_add_node_summary,
                "if_add_doc_description": args.if_add_doc_description,
                "if_add_node_text": args.if_add_node_text,
                "if_add_node_id": args.if_add_node_id,
            }
            opt = config_loader.load(user_opt)
            print("Processing markdown file...")
            toc_with_page_number = _run_md_to_tree(str(md_path), args, opt)
            flash = False
        elif args.flash:
            from pageindex.flash import page_index_flash
            toc_with_page_number = page_index_flash(args.pdf_path)
            flash = True
        else:
            user_opt = {
                "model": args.model,
                "toc_check_page_num": args.toc_check_pages,
                "max_page_num_each_node": args.max_pages_per_node,
                "max_token_num_each_node": args.max_tokens_per_node,
                "if_add_node_id": args.if_add_node_id,
                "if_add_node_summary": args.if_add_node_summary,
                "if_add_doc_description": args.if_add_doc_description,
                "if_add_node_text": args.if_add_node_text,
            }
            opt = ConfigLoader().load({k: v for k, v in user_opt.items() if v is not None})
            toc_with_page_number = page_index_main(args.pdf_path, opt)
            flash = False

        print("Parsing done, saving to file...")
        output_file = _save_structure(toc_with_page_number, pdf_name, args.catalog, flash=flash)
        print(f"Tree structure saved to: {output_file}")

    elif args.md_path:
        if not args.md_path.lower().endswith((".md", ".markdown")):
            raise ValueError("Markdown file must have .md or .markdown extension")
        if not os.path.isfile(args.md_path):
            raise ValueError(f"Markdown file not found: {args.md_path}")

        print("Processing markdown file...")
        config_loader = ConfigLoader()
        user_opt = {
            "model": args.model,
            "if_add_node_summary": args.if_add_node_summary,
            "if_add_doc_description": args.if_add_doc_description,
            "if_add_node_text": args.if_add_node_text,
            "if_add_node_id": args.if_add_node_id,
        }
        opt = config_loader.load(user_opt)
        toc_with_page_number = _run_md_to_tree(args.md_path, args, opt)

        print("Parsing done, saving to file...")
        md_name = os.path.splitext(os.path.basename(args.md_path))[0]
        output_file = _save_structure(toc_with_page_number, md_name, args.catalog)
        print(f"Tree structure saved to: {output_file}")
