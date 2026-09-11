"""External plugin example — `d2w hello`.

Registration happens via `[project.entry-points."dhis2w.plugins.v1"]` in the
package's `pyproject.toml`. Once this package is installed in the same
environment as `dhis2w-core`, the pluginkit host discovers it automatically —
no core code change needed.
"""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _HelloPlugin:
    """Plugin object — the entry-point attribute dhis2w-core imports."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w hello` and the `hello_say` MCP tool."""
        return Contribution(
            name="hello",
            description=(
                "External plugin example — greets the authenticated user via /api/me. "
                "Install with `uv add --editable examples/plugin-external/` to see it register."
            ),
            cli_module="dhis2w_plugin_hello.cli",
            mcp_module="dhis2w_plugin_hello.mcp",
        )


plugin = _HelloPlugin()
