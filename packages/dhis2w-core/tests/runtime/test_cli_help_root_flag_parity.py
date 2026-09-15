"""Per-version parity for command help that points at the root `--json` flag.

`--json` is declared once on the root callback, so the payload comes from
`d2w --json metadata get ...` and `d2w metadata get <uid> --json` is rejected by the
parser. A command whose help names the flag therefore has to show that position.
These tests read the rendered help on all three trees (v41/v42/v43) and pin both the
wording and the parser behaviour it describes.
"""

from __future__ import annotations

import json
import re
from importlib import import_module
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from dhis2w_cli.main import build_app
from typer import Typer
from typer.testing import CliRunner

_JSON_HELP_COMMANDS = [
    ["metadata", "get"],
    ["system", "whoami"],
    ["user", "get"],
    ["user", "group", "get"],
    ["user", "group", "sharing-get"],
    ["user", "role", "get"],
]


def _build_versioned_app(core_version: str, monkeypatch: pytest.MonkeyPatch) -> Typer:
    """Build the CLI app pinned to `core_version` (so it discovers that tree's plugins)."""
    monkeypatch.setenv("DHIS2_VERSION", core_version)
    monkeypatch.setenv("COLUMNS", "200")
    return build_app()


def _help_text(core_version: str, monkeypatch: pytest.MonkeyPatch, command: list[str]) -> str:
    """Render one command's `--help` output with its line wrapping collapsed to single spaces."""
    app = _build_versioned_app(core_version, monkeypatch)
    result = CliRunner().invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    return re.sub(r"\s+", " ", result.output)


def _options_panel(core_version: str, monkeypatch: pytest.MonkeyPatch, command: list[str]) -> str:
    """Render the Options panel of one command's `--help`, without the summary paragraph."""
    app = _build_versioned_app(core_version, monkeypatch)
    result = CliRunner().invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    _, _, panel = result.output.partition("Options")
    return panel


def test_metadata_get_help_names_the_root_flag(core_version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`d2w metadata get --help` says `--json` is a root flag and shows it before the subcommand."""
    text = _help_text(core_version, monkeypatch, ["metadata", "get"])
    assert "`--json` is a root flag" in text
    assert "d2w --json metadata get" in text


def test_metadata_get_help_offers_no_local_json_option(core_version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`d2w metadata get --help` lists `--fields` and `--help` in Options, never `--json`."""
    panel = _options_panel(core_version, monkeypatch, ["metadata", "get"])
    assert "--fields" in panel
    assert "--json" not in panel


@pytest.mark.parametrize("command", _JSON_HELP_COMMANDS, ids=lambda command: " ".join(command))
def test_json_help_commands_name_the_root_position(
    core_version: str,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> None:
    """Every command whose help mentions `--json` spells the root invocation and offers no local flag."""
    text = _help_text(core_version, monkeypatch, command)
    assert f"d2w --json {' '.join(command)}" in text
    assert "--json" not in _options_panel(core_version, monkeypatch, command)


def test_metadata_get_rejects_a_trailing_json_flag(core_version: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`d2w metadata get <resource> <uid> --json` is a parse error — the flag is not the command's own."""
    app = _build_versioned_app(core_version, monkeypatch)
    result = CliRunner().invoke(app, ["metadata", "get", "dataElements", "aBcDeFgHiJ1", "--json"])
    assert result.exit_code != 0
    assert "No such option" in result.output


def test_metadata_get_takes_the_root_json_flag_the_help_recommends(
    core_version: str,
    core_profile: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`d2w --json metadata get <resource> <uid>` prints the full payload, exactly as the help says."""
    data_element_cls = import_module(f"dhis2w_client.{core_version}").DataElement
    model: Any = data_element_cls.model_validate({"id": "aBcDeFgHiJ1", "name": "BCG doses given"})
    with patch(
        f"dhis2w_core.{core_version}.plugins.metadata.service.get_metadata",
        new=AsyncMock(return_value=model),
    ):
        app = _build_versioned_app(core_version, monkeypatch)
        result = CliRunner().invoke(app, ["--json", "-p", "probe", "metadata", "get", "dataElements", "aBcDeFgHiJ1"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["id"] == "aBcDeFgHiJ1"
