---
title: Project
---

# Project

The living record of the toolkit: what it does today, what changed, what is
planned, and the upstream quirks worked around along the way. These pages are
the meta layer around the surface docs (Client, CLI, and the MCP pack's own site) and the architecture
reference.

<div class="grid cards" markdown>

- **Feature catalog**

    ---

    Every user-visible capability across the published packages and the three
    version trees, grouped by surface.

    [Browse the catalog](features.md)

- **Changelog**

- **Roadmap**

    ---

    Current state, gaps surfaced during use, the near-term slate, and the
    strategic options under consideration.

    [See the roadmap](../roadmap.md)

- **FHIR design**

    ---

    The `dhis2w-fhir` pack's roadmap and review guide, the conversion layer,
    corrections and withdrawals, the DHIS2 fidelity audit, and harmonization
    across country guides, in the pack's own documentation.

    [Open the FHIR design pages](https://winterop-com.github.io/dhis2w-fhir/design/roadmap/)

- **Upstream DHIS2 quirks**

    ---

    The catalogue of upstream DHIS2 bugs and surprises, each with a `curl` repro
    and the workaround applied in this repo.

    [Review the quirks](upstream-quirks.md)

- **Decisions and lessons**

    ---

    The maintainer-facing decisions log and lessons learned during development.

    [Decisions](../decisions.md) | [Lessons](../lessons.md)

</div>

## How these pages stay current

- **Feature catalog** is hand-maintained; the auto-generated
  [CLI reference](../cli-reference.md) and [MCP reference](https://winterop-com.github.io/dhis2w-mcp/tool-reference/)
  are the source of truth when a count drifts.
- **Upstream quirks** and the **planning** pages render their repository-root
  source files (`BUGS.md`, the migration plan) directly, so editing the root
  file updates the site on the next build.
- **Roadmap** describes what is next, never what shipped; finished items are
  deleted from it rather than rewritten into history.
