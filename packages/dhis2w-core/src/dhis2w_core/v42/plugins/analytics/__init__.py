"""Analytics plugin — CLI wrappers over /api/analytics and /api/resourceTables/analytics."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _AnalyticsPlugin:
    """Plugin descriptor for DHIS2 analytics queries."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w analytics`; its MCP tools are the dhis2w-mcp pack's."""
        return Contribution(
            name="analytics",
            description="Run DHIS2 analytics queries (aggregated, raw, dataValueSet) and trigger refresh.",
            cli_module="dhis2w_core.v42.plugins.analytics.cli",
            mcp_module=None,
        )


plugin = _AnalyticsPlugin()
