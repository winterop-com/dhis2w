"""Doctor plugin — probe a DHIS2 instance for known BUGS.md gotchas + workspace hard requirements."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _DoctorPlugin:
    """Plugin descriptor for `d2w doctor`."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w doctor` and the `doctor_run` MCP tool."""
        return Contribution(
            name="doctor",
            description=(
                "Probe a DHIS2 instance for known BUGS.md gotchas + workspace hard requirements. One command, pure "
                "reads, pass/warn/fail per probe with BUGS.md cross-refs."
            ),
            cli_module="dhis2w_core.v43.plugins.doctor.cli",
            mcp_module="dhis2w_core.v43.plugins.doctor.mcp",
        )


plugin = _DoctorPlugin()
