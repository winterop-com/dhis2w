"""Apps plugin — DHIS2 `/api/apps` + `/api/appHub`."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _AppsPlugin:
    """Plugin descriptor for DHIS2 apps — install / uninstall / update / App Hub queries."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w apps`; its MCP tools are the dhis2w-mcp pack's."""
        return Contribution(
            name="apps",
            description=(
                "DHIS2 apps: `/api/apps` + `/api/appHub`. CLI for list, add (from local zip or App Hub "
                "version), remove, update (one / --all), reload."
            ),
            cli_module="dhis2w_core.v44.plugins.apps.cli",
            mcp_module=None,
        )


plugin = _AppsPlugin()
