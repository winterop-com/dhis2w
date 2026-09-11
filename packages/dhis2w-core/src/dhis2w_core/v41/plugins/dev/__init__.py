"""Dev plugin — `d2w dev` for operator / developer one-off tools (codegen, uid, oauth2 client)."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _DevPlugin:
    """Plugin descriptor for developer + operator tools."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w dev`; the developer tools are CLI-only."""
        return Contribution(
            name="dev",
            description="Developer/operator tools: codegen, UID generation, sample data.",
            cli_module="dhis2w_core.v41.plugins.dev.cli",
            mcp_module=None,
        )


plugin = _DevPlugin()
