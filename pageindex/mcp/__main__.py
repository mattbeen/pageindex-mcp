"""CLI entry point: stdio (default) or streamable HTTP with --http."""

from __future__ import annotations

import argparse
import os
import sys

from mcp.server.transport_security import TransportSecuritySettings

from pageindex.mcp.server import mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pageindex.mcp",
        description="PageIndex MCP server (CLI catalog workspaces)",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run streamable HTTP transport (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=(
            "HTTP bind address. Use 0.0.0.0 to accept LAN/IP connections "
            "(default: PAGEINDEX_MCP_HTTP_HOST or 127.0.0.1)."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP port (default: PAGEINDEX_MCP_HTTP_PORT or 8765).",
    )
    args = parser.parse_args(argv)

    if args.http:
        # 0.0.0.0 = all interfaces (reachable via machine IP); 127.0.0.1 = localhost only
        mcp.settings.host = (
            args.host
            or os.getenv("PAGEINDEX_MCP_HTTP_HOST")
            or "127.0.0.1"
        )
        mcp.settings.port = int(
            args.port
            if args.port is not None
            else os.getenv("PAGEINDEX_MCP_HTTP_PORT", "8765")
        )
        mcp.settings.streamable_http_path = os.getenv(
            "PAGEINDEX_MCP_HTTP_PATH", "/mcp/page-index/v1"
        )
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
        print(
            f"PageIndex MCP HTTP listening on http://{mcp.settings.host}:{mcp.settings.port}"
            f"{mcp.settings.streamable_http_path}",
            file=sys.stderr,
        )
        if mcp.settings.host in ("0.0.0.0", "::"):
            print(
                "Bound to all interfaces — connect via http://<this-host-ip>:"
                f"{mcp.settings.port}{mcp.settings.streamable_http_path}",
                file=sys.stderr,
            )
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
