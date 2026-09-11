"""Browser plugin — Playwright-driven DHIS2 UI automation.

Mounts `d2w browser ...` subcommands only when the optional
`dhis2w-browser` library is importable. Installations that skip the
`[browser]` extra get nothing — the command silently drops out of
`d2w --help` rather than showing a broken entry.
"""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _BrowserPlugin:
    """Plugin descriptor for Playwright-driven DHIS2 UI automation."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w browser`; the Playwright flows are CLI-only."""
        return Contribution(
            name="browser",
            description=(
                "Playwright-driven DHIS2 UI automation. Mounts `d2w browser ...` for workflows DHIS2 only exposes "
                "through the web UI (PAT minting today; dashboard screenshots + maintenance-app driving planned)."
            ),
            cli_module="dhis2w_core.v42.plugins.browser.cli",
            mcp_module=None,
        )


plugin = _BrowserPlugin()
