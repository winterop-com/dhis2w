"""`d2w <command>` for a known pack that is not installed prints how to install it."""

from __future__ import annotations

import typer
from dhis2w_cli.packs import OPTIONAL_PACKS, install_hint, mount_install_hints
from typer.testing import CliRunner


def _app(mounted: tuple[str, ...]) -> typer.Typer:
    """A bare root app with the install hints mounted beside the given plugin names."""
    app = typer.Typer(add_completion=False)

    @app.callback()
    def _root() -> None:
        """Root."""

    mount_install_hints(app, mounted)
    return app


def test_a_missing_pack_prints_its_install_command() -> None:
    result = CliRunner().invoke(_app(()), ["fhir", "init", "national", "--with-registry"])
    assert result.exit_code == 1
    assert 'uv tool install "dhis2w-cli[fhir]"' in result.output
    assert "dhis2w-fhir" in result.output


def test_every_known_pack_has_a_hint_when_missing() -> None:
    runner = CliRunner()
    for pack in OPTIONAL_PACKS:
        result = runner.invoke(_app(()), [pack.command])
        assert result.exit_code == 1
        assert install_hint(pack) in result.output


def test_an_installed_pack_gets_no_hint() -> None:
    app = _app(("fhir",))
    result = CliRunner().invoke(app, ["fhir"])
    assert result.exit_code != 1 or "uv tool install" not in result.output


def test_the_hints_are_hidden_from_help() -> None:
    result = CliRunner().invoke(_app(()), ["--help"])
    assert "fhir" not in result.output
