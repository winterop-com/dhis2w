"""System plugin — exposes /api/system/info and /api/me as CLI + MCP surfaces."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _SystemPlugin:
    """Plugin descriptor for the system capability."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w system` and the `whoami` / `system_info` MCP tools."""
        return Contribution(
            name="system",
            description="DHIS2 system info and current-user access.",
            cli_module="dhis2w_core.v43.plugins.system.cli",
            mcp_module="dhis2w_core.v43.plugins.system.mcp",
        )


plugin = _SystemPlugin()
