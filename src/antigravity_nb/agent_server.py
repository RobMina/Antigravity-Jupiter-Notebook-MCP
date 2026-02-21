from __future__ import annotations

import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any, Callable

from .agent import NotebookToolManager

logger = logging.getLogger(__name__)

ToolFn = Callable[[dict[str, Any]], dict[str, Any]]

_MCP_PROTOCOL_VERSION = "2024-11-05"


def _tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "open_notebook",
            "description": "Open a notebook and return its metadata (cell count, pipeline stages).",
            "inputSchema": {
                "type": "object",
                "properties": {"notebook_path": {"type": "string"}},
                "required": ["notebook_path"],
            },
        },
        {
            "name": "list_cells",
            "description": "List all cells in a notebook with their index, type, tags, and an optional source preview.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_path": {"type": "string"},
                    "include_source": {"type": "boolean", "description": "Include full source for every cell (default false)."},
                    "preview_chars": {"type": "integer", "description": "Characters of source to include as preview (default 120)."},
                },
                "required": ["notebook_path"],
            },
        },
        {
            "name": "read_cell",
            "description": "Read the full source, outputs, and metadata of a single cell.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_path": {"type": "string"},
                    "index": {"type": "integer"},
                },
                "required": ["notebook_path", "index"],
            },
        },
        {
            "name": "edit_cell",
            "description": "Replace the source of a cell. Creates a timestamped checkpoint by default.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_path": {"type": "string"},
                    "index": {"type": "integer"},
                    "source": {"type": "string"},
                    "save": {"type": "boolean"},
                    "checkpoint": {"type": "boolean"},
                },
                "required": ["notebook_path", "index", "source"],
            },
        },
        {
            "name": "insert_cell",
            "description": "Insert a new cell at the given index, shifting later cells down.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_path": {"type": "string"},
                    "index": {"type": "integer"},
                    "cell_type": {"type": "string", "enum": ["code", "markdown", "raw"]},
                    "source": {"type": "string"},
                    "save": {"type": "boolean"},
                    "checkpoint": {"type": "boolean"},
                },
                "required": ["notebook_path", "index"],
            },
        },
        {
            "name": "delete_cell",
            "description": "Delete the cell at the given index. Creates a timestamped checkpoint by default.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_path": {"type": "string"},
                    "index": {"type": "integer"},
                    "save": {"type": "boolean"},
                    "checkpoint": {"type": "boolean"},
                },
                "required": ["notebook_path", "index"],
            },
        },
        {
            "name": "run_cell",
            "description": "Execute a single code cell and return its outputs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_path": {"type": "string"},
                    "index": {"type": "integer"},
                    "timeout": {"type": "integer", "description": "Seconds before timing out (default 120)."},
                    "save": {"type": "boolean"},
                    "kernel_name": {"type": "string"},
                },
                "required": ["notebook_path", "index"],
            },
        },
        {
            "name": "run_range",
            "description": "Execute all code cells in the inclusive range [start, end].",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_path": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "timeout": {"type": "integer"},
                    "stop_on_error": {"type": "boolean"},
                    "save": {"type": "boolean"},
                    "kernel_name": {"type": "string"},
                },
                "required": ["notebook_path", "start", "end"],
            },
        },
        {
            "name": "run_pipeline",
            "description": "Execute cells grouped by their tag-based pipeline stages.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_path": {"type": "string"},
                    "stage_order": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Stage names to run in order. Defaults to all stages in notebook order.",
                    },
                    "timeout": {"type": "integer"},
                    "stop_on_error": {"type": "boolean"},
                    "save": {"type": "boolean"},
                    "kernel_name": {"type": "string"},
                },
                "required": ["notebook_path"],
            },
        },
        {
            "name": "restart_kernel",
            "description": "Restart the Jupyter kernel for a notebook, clearing all in-memory state.",
            "inputSchema": {
                "type": "object",
                "properties": {"notebook_path": {"type": "string"}},
                "required": ["notebook_path"],
            },
        },
    ]


class StdioToolServer:
    def __init__(self, workspace_root: str | Path = ".", default_kernel: str = "python3") -> None:
        self.manager = NotebookToolManager(workspace_root=workspace_root, default_kernel=default_kernel)
        self.tools: dict[str, ToolFn] = {
            "open_notebook": lambda a: self.manager.open_notebook(a["notebook_path"]),
            "list_cells": lambda a: self.manager.list_cells(
                a["notebook_path"],
                include_source=a.get("include_source", False),
                preview_chars=a.get("preview_chars", 120),
            ),
            "read_cell": lambda a: self.manager.read_cell(a["notebook_path"], a["index"]),
            "edit_cell": lambda a: self.manager.edit_cell(
                a["notebook_path"],
                a["index"],
                a["source"],
                save=a.get("save", True),
                checkpoint=a.get("checkpoint", True),
            ),
            "insert_cell": lambda a: self.manager.insert_cell(
                a["notebook_path"],
                a["index"],
                cell_type=a.get("cell_type", "code"),
                source=a.get("source", ""),
                save=a.get("save", True),
                checkpoint=a.get("checkpoint", False),
            ),
            "delete_cell": lambda a: self.manager.delete_cell(
                a["notebook_path"],
                a["index"],
                save=a.get("save", True),
                checkpoint=a.get("checkpoint", True),
            ),
            "run_cell": lambda a: self.manager.run_cell(
                a["notebook_path"],
                a["index"],
                timeout=a.get("timeout", 120),
                save=a.get("save", True),
                kernel_name=a.get("kernel_name"),
            ),
            "run_range": lambda a: self.manager.run_range(
                a["notebook_path"],
                a["start"],
                a["end"],
                timeout=a.get("timeout", 120),
                stop_on_error=a.get("stop_on_error", True),
                save=a.get("save", True),
                kernel_name=a.get("kernel_name"),
            ),
            "run_pipeline": lambda a: self.manager.run_pipeline(
                a["notebook_path"],
                stage_order=a.get("stage_order"),
                timeout=a.get("timeout", 120),
                stop_on_error=a.get("stop_on_error", True),
                save=a.get("save", True),
                kernel_name=a.get("kernel_name"),
            ),
            "restart_kernel": lambda a: self.manager.restart_kernel(a["notebook_path"]),
        }

    def _ok(self, req_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _err(self, req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    def _handle(self, req: dict[str, Any]) -> dict[str, Any] | None:
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        # MCP notifications have no "id" and require no response.
        if "id" not in req:
            logger.debug("notification: %s", method)
            return None

        logger.debug("request id=%s method=%s", req_id, method)

        if method == "initialize":
            return self._ok(req_id, {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "antigravity-nb", "version": "0.1.0"},
            })
        if method == "tools/list":
            return self._ok(req_id, {"tools": _tool_schemas()})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name not in self.tools:
                return self._err(req_id, -32601, f"Unknown tool: {name!r}")
            try:
                result = self.tools[name](arguments)
                logger.debug("tool %s ok", name)
                return self._ok(req_id, {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                    "isError": False,
                })
            except Exception as exc:
                logger.warning("tool %s error: %s", name, exc)
                return self._ok(req_id, {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                })
        if method == "shutdown":
            self.manager.shutdown_all()
            return self._ok(req_id, {"ok": True})
        return self._err(req_id, -32601, f"Unknown method: {method!r}")

    def serve_forever(self) -> None:
        logger.info(
            "antigravity-nb MCP server started (workspace=%s)",
            self.manager.workspace_root,
        )

        def _on_signal(signum: int, _frame: Any) -> None:
            logger.info("received signal %d, shutting down", signum)
            self.manager.shutdown_all()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("parse error: %s", exc)
                sys.stdout.write(json.dumps(self._err(None, -32700, f"Parse error: {exc}")) + "\n")
                sys.stdout.flush()
                continue
            resp = self._handle(req)
            if resp is None:
                continue  # notification — no response
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        logger.info("stdin closed, shutting down")


def run_stdio_server(workspace_root: str = ".", default_kernel: str = "python3") -> int:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    server = StdioToolServer(workspace_root=workspace_root, default_kernel=default_kernel)
    try:
        server.serve_forever()
        return 0
    finally:
        server.manager.shutdown_all()
