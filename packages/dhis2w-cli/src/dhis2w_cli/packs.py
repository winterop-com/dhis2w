"""The optional plugin packs `d2w` knows by name, and the hint it prints when one is not installed."""

from __future__ import annotations

from collections.abc import Callable

import typer
from pydantic import BaseModel, ConfigDict


class OptionalPack(BaseModel):
    """A plugin pack that mounts a `d2w` command group when installed, and the extra that installs it."""

    model_config = ConfigDict(frozen=True)

    command: str
    distribution: str
    extra: str
    summary: str


OPTIONAL_PACKS: tuple[OptionalPack, ...] = (
    OptionalPack(
        command="fhir",
        distribution="dhis2w-fhir",
        extra="fhir",
        summary="FHIR Implementation Guides from DHIS2 metadata, and the capture server",
    ),
    OptionalPack(
        command="browser",
        distribution="dhis2w-browser",
        extra="browser",
        summary="Playwright-driven DHIS2 UI automation",
    ),
    OptionalPack(
        command="security",
        distribution="dhis2w-security",
        extra="security",
        summary="a security audit of a DHIS2 instance",
    ),
)


def install_hint(pack: OptionalPack) -> str:
    """The message `d2w <command>` prints when the pack providing it is not installed."""
    return (
        f"`d2w {pack.command}` is not installed. It comes with the {pack.distribution} pack "
        f"({pack.summary}):\n\n"
        f'  uv tool install "dhis2w-cli[{pack.extra}]"\n\n'
        f"or, in a project: uv add {pack.distribution}"
    )


def _hint_command(pack: OptionalPack) -> Callable[[typer.Context], None]:
    """The command body standing in for `d2w <command>`: print the install hint and exit 1."""

    def _hint(context: typer.Context) -> None:
        typer.echo(install_hint(pack), err=True)
        raise typer.Exit(1)

    return _hint


def mount_install_hints(app: typer.Typer, mounted: tuple[str, ...]) -> None:
    """Mount a hidden `d2w <command>` for every known pack that is not installed, printing how to install it."""
    for pack in OPTIONAL_PACKS:
        if pack.command in mounted:
            continue
        app.command(
            pack.command,
            hidden=True,
            add_help_option=False,
            context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
        )(_hint_command(pack))
