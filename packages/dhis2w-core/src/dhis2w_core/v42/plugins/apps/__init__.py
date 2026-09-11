"""Apps plugin — DHIS2 `/api/apps` + `/api/appHub`."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _AppsPlugin:
    """Plugin descriptor for DHIS2 apps — install / uninstall / update / App Hub queries."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w apps` and the `apps_*` MCP tools."""
        return Contribution(
            name="apps",
            description=(
                "DHIS2 apps: `/api/apps` + `/api/appHub`. CLI + MCP surfaces for list, add (from local zip or App Hub "
                "version), remove, update (one / --all), reload."
            ),
            cli_module="dhis2w_core.v42.plugins.apps.cli",
            mcp_module="dhis2w_core.v42.plugins.apps.mcp",
        )


plugin = _AppsPlugin()
