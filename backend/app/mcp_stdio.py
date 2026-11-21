"""Run ShelfLife's MCP server over stdio, for MCP clients that launch it themselves.

    uv run python -m app.mcp_stdio

Messages are newline-delimited JSON-RPC on stdin and stdout. Logs go to stderr.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from app import config, demo, mcp


async def serve() -> None:
    if config.get_settings().demo_mode:
        demo.activate()
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error."}}
        else:
            response = await mcp.handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    asyncio.run(serve())
