"""Analytics plugin — CLI + MCP wrappers over /api/analytics and /api/resourceTables/analytics."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _AnalyticsPlugin:
    """Plugin descriptor for DHIS2 analytics queries."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w analytics` and the analytics MCP tools."""
        return Contribution(
            name="analytics",
            description="Run DHIS2 analytics queries (aggregated, raw, dataValueSet) and trigger refresh.",
            cli_module="dhis2w_core.v43.plugins.analytics.cli",
            mcp_module="dhis2w_core.v43.plugins.analytics.mcp",
        )


plugin = _AnalyticsPlugin()
