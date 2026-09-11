"""User plugin — list, get, invite, reinvite, and password-reset for DHIS2 users."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _UserPlugin:
    """Plugin descriptor for the DHIS2 user administration surface."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w user` and the user MCP tools."""
        return Contribution(
            name="user",
            description="List + administer DHIS2 users (invite, reinvite, password reset).",
            cli_module="dhis2w_core.v43.plugins.user.cli",
            mcp_module="dhis2w_core.v43.plugins.user.mcp",
        )


plugin = _UserPlugin()
