"""Smoke matrix for the v41 plugin tree — host loading + import-time correctness.

Verifies every plugin under `dhis2w_core.v41.plugins.*` contributes cleanly
when picked up by `load_plugin_host("v41")`. Catches import-time failures
that would otherwise only surface when a v41-stack CLI/MCP user invokes
a specific plugin. Pairs with `test_v43_plugin_smoke.py`.
"""

from __future__ import annotations

from dhis2w_core.plugin import load_plugin_host

EXPECTED_PLUGINS = {
    "analytics",
    "apps",
    "browser",
    "customize",
    "data",  # mounts aggregate + tracker as sub-commands
    "dev",
    "fhir",
    "doctor",
    "files",
    "maintenance",
    "messaging",
    "metadata",
    "profile",
    "route",
    "system",
    "user",
    "user-group",
    "user-role",
}


def test_v41_host_returns_full_set() -> None:
    """v41 host loading returns full set."""
    host = load_plugin_host("v41")
    assert set(host.names) >= EXPECTED_PLUGINS
    assert host.failures == ()


def test_v41_every_contribution_is_complete() -> None:
    """v41 every contribution carries a name, a description, and at least one surface."""
    for contribution in load_plugin_host("v41").contributions:
        assert contribution.name
        assert contribution.description
        assert contribution.cli_module is not None or contribution.mcp_module is not None


def test_v41_system_plugin_is_v41_bound() -> None:
    """v41 system plugin is v41 bound."""
    system = load_plugin_host("v41").get("system")
    assert system is not None
    # The named modules live under dhis2w_core.v41.plugins.system, confirming
    # we got the v41 tree (and not v42 by accident).
    assert system.cli_module == "dhis2w_core.v41.plugins.system.cli"
    assert system.mcp_module == "dhis2w_core.v41.plugins.system.mcp"
