"""Metadata plugin — CLI wrappers over the generated CRUD resources."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _MetadataPlugin:
    """Plugin descriptor for DHIS2 metadata inspection."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w metadata`; its MCP tools are the dhis2w-mcp pack's."""
        return Contribution(
            name="metadata",
            description="Inspect DHIS2 metadata (lists + get by UID, across every generated resource).",
            cli_module="dhis2w_core.v44.plugins.metadata.cli",
            mcp_module=None,
        )


plugin = _MetadataPlugin()
