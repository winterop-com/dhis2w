"""Per-version MCP registration parity — register every plugin's tools on all three trees.

The service parity tests cover the service layer; this registers each version tree's contributions
onto a FastMCP server, executing every plugin's `mcp.py` `register` body + `@mcp.tool` definitions
across v41/v42/v43. It needs no connection — registration only defines tools.
"""

from __future__ import annotations

from dhis2w_core.plugin import load_plugin_host
from fastmcp import FastMCP


def test_mcp_register_all_plugins_parity(core_version: str) -> None:
    """Every plugin in the version tree registers its MCP tools cleanly, on every version tree."""
    server: FastMCP = FastMCP("parity")
    host = load_plugin_host(core_version)
    host.register_mcp(server)
    assert host.contributions, f"no plugins discovered for {core_version}"
