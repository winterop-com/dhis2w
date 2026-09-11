"""Customize plugin — brand + theme a DHIS2 instance.

CLI is mounted under `d2w dev customize` (see `plugins/dev/cli.py`),
alongside the other rarely-run setup utilities (`dev pat`, `dev oauth2`,
`dev sample`, `dev codegen`). MCP tools are registered at the top level
(`customize_*`) since MCP has no nested-namespace convention.
"""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _CustomizePlugin:
    """Plugin descriptor for DHIS2 branding + theming."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute the customize CLI sub-app and the `customize_*` MCP tools."""
        return Contribution(
            name="customize",
            description=(
                "DHIS2 branding + theming: login-page logos, system-setting copy, CSS stylesheet. Applies preset "
                "directories so `d2w dev customize apply DIR` re-brands an instance."
            ),
            cli_module="dhis2w_core.v42.plugins.customize.cli",
            mcp_module="dhis2w_core.v42.plugins.customize.mcp",
        )


plugin = _CustomizePlugin()
