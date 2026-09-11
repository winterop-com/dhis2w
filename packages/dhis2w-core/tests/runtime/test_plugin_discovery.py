"""Unit tests for the dhis2w-core plugin host + version-aware startup wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import typer
from dhis2w_client import Dhis2
from dhis2w_core.plugin import DEFAULT_VERSION_KEY, Contribution, extension, load_plugin_host, resolve_startup_version
from dhis2w_core.profile import Profile, ProfilesFile, write_profiles_file


class _StubPlugin:
    """A plugin object registered through `extra=` rather than an entry point."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute a CLI-less, MCP-less stub so the host has something to collect."""
        return Contribution(name="stub", description="Stub plugin for the host tests.")


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every profile-related env var so tests start from a known state."""
    for key in ("DHIS2_PROFILE", "DHIS2_URL", "DHIS2_PAT", "DHIS2_USERNAME", "DHIS2_PASSWORD", "DHIS2_VERSION"):
        monkeypatch.delenv(key, raising=False)


def test_host_includes_system() -> None:
    """The host collects the built-in system plugin."""
    assert "system" in load_plugin_host().names


def test_system_contribution_names_both_surfaces() -> None:
    """The system contribution names a CLI module, an MCP module, and a description."""
    system = load_plugin_host().get("system")
    assert system is not None
    assert system.cli_module is not None
    assert system.mcp_module is not None
    assert system.description


def test_default_version_is_v43() -> None:
    """v43 is the canonical baseline so no-config bootstrap lands there."""
    assert DEFAULT_VERSION_KEY == "v43"


def test_host_default_matches_explicit_v43() -> None:
    """`load_plugin_host()` with no arg walks the v43 plugin tree."""
    default_names = load_plugin_host().names
    explicit_names = load_plugin_host("v43").names
    assert default_names == explicit_names
    assert len(default_names) > 0


@pytest.mark.parametrize("version_key", ["v41", "v42", "v43"])
def test_host_finds_each_version_tree(version_key: str) -> None:
    """Each `v{N}/plugins/` tree carries the same plugin set today (mechanical copies)."""
    names = set(load_plugin_host(version_key).names)
    assert "metadata" in names
    assert "system" in names


def test_host_names_are_sorted() -> None:
    """Contributions come back sorted by name so the command tree is stable."""
    names = load_plugin_host().names
    assert list(names) == sorted(names)


def test_unknown_tree_yields_only_entry_point_contributions() -> None:
    """A bogus version_key picks up no built-ins; entry-point packs still contribute."""
    builtin_names = {"metadata", "system", "tracker", "aggregate"}
    host = load_plugin_host("v99")
    assert not (builtin_names & set(host.names))
    assert "fhir" in host.names


def test_unknown_group_yields_the_builtins_only() -> None:
    """An entry-point group nobody advertises leaves the built-ins as the whole host."""
    host = load_plugin_host("v43", group="dhis2w.plugins.nonexistent")
    assert "system" in host.names
    assert "fhir" not in host.names
    assert host.failures == ()


def test_extra_registers_a_plugin_object() -> None:
    """`extra=` registers a plugin object under the given name and its contribution is mounted."""
    host = load_plugin_host("v43", extra={"stub": _StubPlugin()})
    stub = host.get("stub")
    assert stub is not None
    assert stub.description == "Stub plugin for the host tests."
    root = typer.Typer()
    stub.mount_cli(root)


def test_contribution_without_modules_mounts_nothing() -> None:
    """A contribution with `cli_module=None` mounts no command and registers no tool."""
    contribution = Contribution(name="quiet", description="Contributes no surface at all.")
    root = typer.Typer()
    contribution.mount_cli(root)
    assert not root.registered_groups
    assert not root.registered_commands

    class _Recorder:
        """A stand-in MCP server that would record any registration attempt."""

        def __init__(self) -> None:
            self.calls: list[Any] = []

    recorder = _Recorder()
    contribution.register_mcp(recorder)
    assert recorder.calls == []


def test_resolve_startup_version_defaults_when_no_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No profile configured -> v43 fallback."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    assert resolve_startup_version() == "v43"


def test_resolve_startup_version_reads_profile_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Profile with explicit version -> that version key is returned."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    project_dir = tmp_path / "proj"
    write_profiles_file(
        project_dir / ".dhis2" / "profiles.toml",
        ProfilesFile(
            default="local",
            profiles={
                "local": Profile(base_url="http://localhost:8080", auth="pat", token="d2p_x", version=Dhis2.V43),
            },
        ),
    )
    monkeypatch.chdir(project_dir)
    assert resolve_startup_version() == "v43"


def test_resolve_startup_version_defaults_when_profile_has_no_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile present but missing the version field -> v43 fallback (auto-detect at wire time)."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    project_dir = tmp_path / "proj"
    write_profiles_file(
        project_dir / ".dhis2" / "profiles.toml",
        ProfilesFile(
            default="local",
            profiles={"local": Profile(base_url="http://localhost:8080", auth="pat", token="d2p_x")},
        ),
    )
    monkeypatch.chdir(project_dir)
    assert resolve_startup_version() == "v43"
