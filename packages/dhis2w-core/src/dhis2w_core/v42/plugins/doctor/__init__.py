"""Doctor plugin — probe a DHIS2 instance for known DHIS2_ISSUES.md gotchas + workspace hard requirements."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _DoctorPlugin:
    """Plugin descriptor for `d2w doctor`."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w doctor`; its MCP tools are the dhis2w-mcp pack's."""
        return Contribution(
            name="doctor",
            description=(
                "Probe a DHIS2 instance for known DHIS2_ISSUES.md gotchas + workspace hard requirements. One command, "
                "pure reads, pass/warn/fail per probe with DHIS2_ISSUES.md cross-refs."
            ),
            cli_module="dhis2w_core.v42.plugins.doctor.cli",
            mcp_module=None,
        )


plugin = _DoctorPlugin()
