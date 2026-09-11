"""Schema plugin — describe a generated type's fields (`d2w schema <type>`)."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _SchemaPlugin:
    """Plugin descriptor for the offline, read-only `schema` command."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute the `schema` command; the plugin has no MCP surface."""
        return Contribution(
            name="schema",
            description="Describe a generated type's fields (metadata or instance-side).",
            cli_module="dhis2w_core.v42.plugins.schema.cli",
            mcp_module=None,
        )


plugin = _SchemaPlugin()
