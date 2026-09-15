"""MCP tool calls that fail on the profile, or on reaching the instance, return the CLI's own guidance."""

from __future__ import annotations

from pathlib import Path

import pytest
from dhis2w_mcp.server import build_server
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.fixture
def _no_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every profile source: env creds, global TOML, and any project TOML above cwd."""
    for key in ("DHIS2_PROFILE", "DHIS2_URL", "DHIS2_PAT", "DHIS2_USERNAME", "DHIS2_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    empty_config = tmp_path / "xdg"
    empty_config.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(empty_config))
    working_dir = tmp_path / "cwd"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)


async def test_tool_call_without_profile_names_setup_commands(_no_profile_env: None) -> None:
    """The tool error names `d2w profile add <name>` and `d2w profile bootstrap` (hard requirement 1)."""
    server = build_server()
    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("system_info", {})

    message = str(excinfo.value)
    assert "no DHIS2 profile is configured" in message
    assert "d2w profile add" in message
    assert "d2w profile bootstrap" in message


@pytest.fixture
def _unreachable_instance_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured profile naming a port nothing listens on, which is the daily neighbour of no profile."""
    for key in ("DHIS2_PROFILE", "DHIS2_URL", "DHIS2_PAT", "DHIS2_USERNAME", "DHIS2_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    config_dir = tmp_path / "xdg" / "dhis2"
    config_dir.mkdir(parents=True)
    (config_dir / "profiles.toml").write_text(
        """
default = "offline"

[profiles.offline]
base_url = "http://127.0.0.1:1"
auth = "pat"
token = "d2p_test"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    working_dir = tmp_path / "cwd"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)


async def test_tool_call_against_an_unreachable_instance_names_the_url_and_the_next_step(
    _unreachable_instance_env: None,
) -> None:
    """The MCP caller reads what the CLI prints: the sentence, the URL dialled, and the two hint lines."""
    server = build_server()
    async with Client(server) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("system_info", {})

    message = str(excinfo.value)
    assert "cannot reach the DHIS2 instance" in message
    assert "http://127.0.0.1:1/api/system/info" in message
    assert "check the profile's base_url" in message
    assert "d2w profile show" in message
