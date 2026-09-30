"""System plugin — exposes /api/system/info and /api/me as CLI commands; its MCP tools are the dhis2w-mcp pack's."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _SystemPlugin:
    """Plugin descriptor for the system capability."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w system`; its MCP tools are the dhis2w-mcp pack's."""
        return Contribution(
            name="system",
            description="DHIS2 system info and current-user access.",
            cli_module="dhis2w_core.v44.plugins.system.cli",
            mcp_module=None,
        )


plugin = _SystemPlugin()
