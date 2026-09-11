"""User-role plugin — list, get, authorities, grant/revoke users."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _UserRolePlugin:
    """Plugin descriptor for the DHIS2 user-role administration surface."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute the user-role MCP tools; the `user` plugin mounts the CLI under `d2w user role`."""
        return Contribution(
            name="user-role",
            description="List + administer DHIS2 user roles (authorities, user membership).",
            cli_module=None,
            mcp_module="dhis2w_core.v41.plugins.user_role.mcp",
        )


plugin = _UserRolePlugin()
