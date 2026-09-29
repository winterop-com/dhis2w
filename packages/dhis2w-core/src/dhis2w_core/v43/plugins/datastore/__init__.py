"""Datastore plugin — DHIS2 key-value store (/api/dataStore + /api/userDataStore) as a CLI."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _DatastorePlugin:
    """Plugin descriptor for the DHIS2 key-value data store."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w datastore`; its MCP tools are the dhis2w-mcp pack's."""
        return Contribution(
            name="datastore",
            description=(
                "DHIS2 key-value data store: namespaced get/set/delete over /api/dataStore (shared) and "
                "/api/userDataStore (per-user, --user)."
            ),
            cli_module="dhis2w_core.v43.plugins.datastore.cli",
            mcp_module=None,
        )


plugin = _DatastorePlugin()
