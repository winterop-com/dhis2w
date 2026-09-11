"""Route plugin — CLI + MCP wrappers over /api/routes (DHIS2 integration routes)."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _RoutePlugin:
    """Plugin descriptor for the DHIS2 Route API."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w route` and the `route_*` MCP tools."""
        return Contribution(
            name="route",
            description="DHIS2 Route API — register + run integration routes (proxies to external services).",
            cli_module="dhis2w_core.v42.plugins.route.cli",
            mcp_module="dhis2w_core.v42.plugins.route.mcp",
        )


plugin = _RoutePlugin()
