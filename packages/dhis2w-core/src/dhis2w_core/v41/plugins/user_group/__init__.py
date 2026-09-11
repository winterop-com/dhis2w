"""User-group plugin — list, get, membership edits, sharing."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _UserGroupPlugin:
    """Plugin descriptor for the DHIS2 user-group administration surface."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute the user-group MCP tools; the `user` plugin mounts the CLI under `d2w user group`."""
        return Contribution(
            name="user-group",
            description="List + administer DHIS2 user groups (membership, sharing).",
            cli_module=None,
            mcp_module="dhis2w_core.v41.plugins.user_group.mcp",
        )


plugin = _UserGroupPlugin()
