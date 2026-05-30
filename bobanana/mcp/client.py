"""Config-driven MCP tool loading with graceful degradation.

Reads an ``mcp.json`` (Claude/Cursor-style ``mcpServers`` map), connects to each
server, and exposes their tools as LangChain tools that the executor can call.

If the optional dependency is missing, the config is absent, or a server fails to
connect, this logs and returns an empty tool list instead of crashing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List, Tuple

from ..logging_setup import get_logger

log = get_logger("mcp")


class McpManager:
    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)
        self._tools: List = []
        self._status: str = "not loaded"

    @property
    def tools(self) -> List:
        return self._tools

    @property
    def status(self) -> str:
        return self._status

    def _read_connections(self) -> dict:
        if not self.config_path.exists():
            self._status = f"no config at {self.config_path} (skipped)"
            log.info("MCP: %s", self._status)
            return {}
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self._status = f"invalid config: {exc}"
            log.warning("MCP: %s", self._status)
            return {}
        servers = raw.get("mcpServers", raw) if isinstance(raw, dict) else {}
        # normalize: ensure each has a transport
        connections = {}
        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            cfg = dict(cfg)
            if "transport" not in cfg:
                cfg["transport"] = "stdio" if "command" in cfg else "streamable_http"
            connections[name] = cfg
        return connections

    def load(self) -> Tuple[List, str]:
        """Load MCP tools synchronously. Returns (tools, status)."""
        connections = self._read_connections()
        if not connections:
            self._tools = []
            return self._tools, self._status

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError:
            self._status = "langchain-mcp-adapters not installed (skipped)"
            log.warning("MCP: %s", self._status)
            self._tools = []
            return self._tools, self._status

        async def _gather():
            client = MultiServerMCPClient(connections)
            return await client.get_tools()

        try:
            self._tools = asyncio.run(_gather())
            names = [getattr(t, "name", "?") for t in self._tools]
            self._status = f"loaded {len(self._tools)} tool(s) from {len(connections)} server(s): {', '.join(names)}"
            log.info("MCP: %s", self._status)
        except Exception as exc:  # connection / protocol failures must not crash the agent
            self._status = f"load failed: {type(exc).__name__}: {exc}"
            log.error("MCP: %s", self._status)
            self._tools = []
        return self._tools, self._status
