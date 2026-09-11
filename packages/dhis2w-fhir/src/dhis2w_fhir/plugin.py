"""Plugin descriptor - contributes `d2w fhir` through the `dhis2w.plugins.v1` entry point.

The package is version-neutral: the wire client auto-detects the DHIS2 major
on connect, and FSH emission only consumes the reduced source models, so one
plugin serves v41/v42/v43 without per-tree copies.
"""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _FhirPlugin:
    """Plugin descriptor for FHIR IG generation."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w fhir`; the FHIR surface has no MCP tools."""
        return Contribution(
            name="fhir",
            description=(
                "FHIR Implementation Guide generation: scaffold a SUSHI project as a pinned uv project "
                "(`d2w fhir init`), then generate FSH from DHIS2 metadata - terminology, the org-unit registry, "
                "questionnaires with example responses, and the narrative pages (`d2w fhir generate`). "
                "`d2w fhir validate` checks an instance's codes for FHIR-safety and writes md/csv/pdf reports, "
                "and `d2w fhir forward` drains the `d2w fhir serve` capture spool back into DHIS2 - a dry run "
                "by default, `--import` to commit."
            ),
            cli_module="dhis2w_fhir.cli",
        )


plugin = _FhirPlugin()
