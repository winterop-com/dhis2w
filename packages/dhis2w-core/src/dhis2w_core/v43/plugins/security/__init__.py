"""Security plugin: inspect DHIS2 security posture (settings, account authorities)."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _SecurityPlugin:
    """Plugin descriptor for the read-only DHIS2 security surface."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w security` and the read-only `security_*` MCP tools."""
        return Contribution(
            name="security",
            description="Inspect DHIS2 security posture (settings, account authorities).",
            cli_module="dhis2w_core.v43.plugins.security.cli",
            mcp_module="dhis2w_core.v43.plugins.security.mcp",
        )


plugin = _SecurityPlugin()
