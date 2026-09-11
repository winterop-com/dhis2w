"""Datastore plugin — DHIS2 key-value store (/api/dataStore + /api/userDataStore) as CLI + MCP."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _DatastorePlugin:
    """Plugin descriptor for the DHIS2 key-value data store."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w datastore` and the `datastore_*` MCP tools."""
        return Contribution(
            name="datastore",
            description=(
                "DHIS2 key-value data store: namespaced get/set/delete over /api/dataStore (shared) and "
                "/api/userDataStore (per-user, --user)."
            ),
            cli_module="dhis2w_core.v42.plugins.datastore.cli",
            mcp_module="dhis2w_core.v42.plugins.datastore.mcp",
        )


plugin = _DatastorePlugin()
