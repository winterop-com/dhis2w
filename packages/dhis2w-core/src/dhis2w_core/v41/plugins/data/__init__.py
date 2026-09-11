"""Data plugin — `d2w data` umbrella covering aggregate + tracker sub-domains."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _DataPlugin:
    """Plugin descriptor for DHIS2 data values (aggregate + tracker)."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w data` and the `data_aggregate_*` / `data_tracker_*` MCP tools."""
        return Contribution(
            name="data",
            description="DHIS2 data values — aggregate (dataValueSets) and tracker (entities, events, ...).",
            cli_module="dhis2w_core.v41.plugins.data.cli",
            mcp_module="dhis2w_core.v41.plugins.data.mcp",
        )


plugin = _DataPlugin()
