"""Maintenance plugin — tasks, cache, soft-delete cleanup, data-integrity."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _MaintenancePlugin:
    """Plugin descriptor for DHIS2 maintenance (tasks, cache, integrity, cleanup)."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w maintenance` and the maintenance MCP tools."""
        return Contribution(
            name="maintenance",
            description="DHIS2 maintenance: task polling, cache clear, soft-delete cleanup, data-integrity checks.",
            cli_module="dhis2w_core.v41.plugins.maintenance.cli",
            mcp_module="dhis2w_core.v41.plugins.maintenance.mcp",
        )


plugin = _MaintenancePlugin()
