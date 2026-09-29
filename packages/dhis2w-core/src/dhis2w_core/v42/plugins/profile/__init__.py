"""Profile plugin — manage DHIS2 profiles across project and global TOML files."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _ProfilePlugin:
    """Plugin descriptor for DHIS2 profile management."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w profile`; its MCP tools are the dhis2w-mcp pack's."""
        return Contribution(
            name="profile",
            description="List, verify, switch, add, and remove DHIS2 profiles.",
            cli_module="dhis2w_core.v42.plugins.profile.cli",
            mcp_module=None,
        )


plugin = _ProfilePlugin()
