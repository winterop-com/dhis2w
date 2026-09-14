"""A `--fields` selection using a DHIS2 field transformer renders, on every version tree.

`organisationUnits~size` replaces the collection with its count on the wire, a shape the generated
resource model does not declare, so the page is read through `TransformedMetadataRow` instead. A
plain selection still validates through the generated model, and any page DHIS2 answers in a shape
neither model can hold raises `MetadataSelectionError` — the CLI's `error:` line, never a traceback.

Parametrised over v41 / v42 / v43 through the `core_version` fixture. Mocked (respx); no live stack.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from types import ModuleType

import httpx
import pytest
import respx
import typer
from dhis2w_cli.main import build_app
from dhis2w_core.cli_errors import run_app
from dhis2w_core.profile import resolve_profile
from typer.testing import CliRunner

_HOST = "https://dhis2.example"

_SIZE_SELECTION = "id,name,organisationUnits~size"


def _page(rows: list[object]) -> httpx.Response:
    """A `/api/dataSets` page carrying `rows` under the collection key."""
    return httpx.Response(200, json={"dataSets": rows})


@respx.mock
async def test_size_transform_renders_the_count_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """`organisationUnits~size` comes back as the count DHIS2 sent, on every version tree."""
    mock_system_info(core_version)
    service = plugin_service("metadata")
    route = respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=_page([{"id": "DSancMonth1", "name": "ANC monthly", "organisationUnits": 1096}]),
    )

    rows = await service.list_metadata(resolve_profile("probe"), "dataSets", fields=_SIZE_SELECTION)

    assert len(rows) == 1
    assert type(rows[0]).__name__ == "TransformedMetadataRow"
    assert rows[0].id == "DSancMonth1"
    assert rows[0].value("organisationUnits") == 1096
    assert route.calls.last.request.url.params["fields"] == _SIZE_SELECTION


@respx.mock
async def test_size_transform_dumps_the_transformed_column_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """The transformed row dumps to the wire shape the CLI and MCP render, on every version tree."""
    mock_system_info(core_version)
    service = plugin_service("metadata")
    respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=_page([{"id": "DSancMonth1", "name": "ANC monthly", "organisationUnits": 1096}]),
    )

    rows = await service.list_metadata(resolve_profile("probe"), "dataSets", fields=_SIZE_SELECTION)

    assert rows[0].model_dump(by_alias=True, exclude_none=True, mode="json") == {
        "id": "DSancMonth1",
        "name": "ANC monthly",
        "organisationUnits": 1096,
    }


@respx.mock
async def test_transform_streams_every_page_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """`iter_metadata` walks transformed pages too (the `--all` path), on every version tree."""
    mock_system_info(core_version)
    service = plugin_service("metadata")
    respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=_page([{"id": "DSancMonth1", "name": "ANC monthly", "organisationUnits": 1096}]),
    )

    counts = [
        row.value("organisationUnits")
        async for row in service.iter_metadata(
            resolve_profile("probe"),
            "dataSets",
            fields=_SIZE_SELECTION,
            page_size=500,
        )
    ]

    assert counts == [1096]


@respx.mock
async def test_plain_selection_still_validates_through_the_generated_model_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """A selection without a transformer keeps parsing into the generated model, on every tree."""
    mock_system_info(core_version)
    service = plugin_service("metadata")
    respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=_page([{"id": "DSancMonth1", "name": "ANC monthly"}]),
    )

    rows = await service.list_metadata(resolve_profile("probe"), "dataSets", fields="id,name")

    assert type(rows[0]).__name__ == "DataSet"
    assert rows[0].id == "DSancMonth1"


@respx.mock
async def test_get_reads_a_transformed_object_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """`get_metadata` reads a transformed selection on one object too, on every version tree."""
    mock_system_info(core_version)
    service = plugin_service("metadata")
    respx.get(f"{_HOST}/api/dataSets/DSancMonth1").mock(
        return_value=httpx.Response(200, json={"id": "DSancMonth1", "organisationUnits": 1096}),
    )

    row = await service.get_metadata(
        resolve_profile("probe"),
        "dataSets",
        "DSancMonth1",
        fields="id,organisationUnits~size",
    )

    assert row.value("organisationUnits") == 1096


@respx.mock
async def test_untransformed_scalar_names_the_field_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """A page the generated model cannot hold raises an error naming the field, on every tree."""
    mock_system_info(core_version)
    service = plugin_service("metadata")
    respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=_page([{"id": "DSancMonth1", "organisationUnits": 1096}]),
    )

    with pytest.raises(service.MetadataSelectionError) as failure:
        await service.list_metadata(resolve_profile("probe"), "dataSets", fields="id,organisationUnits")

    message = str(failure.value)
    assert "listing dataSets" in message
    assert "`organisationUnits` came back as int" in message
    assert "the DataSet model cannot hold" in message
    assert "for example `id,name`" in message


@respx.mock
async def test_unreadable_transformed_row_is_actionable_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """A transformed page the wrapper cannot take raises the same actionable error, on every tree."""
    mock_system_info(core_version)
    service = plugin_service("metadata")
    respx.get(f"{_HOST}/api/dataSets").mock(return_value=_page(["DSancMonth1", "DSancWeekly1"]))

    with pytest.raises(service.MetadataSelectionError) as failure:
        await service.list_metadata(resolve_profile("probe"), "dataSets", fields=_SIZE_SELECTION)

    message = str(failure.value)
    assert "listing dataSets" in message
    assert "this client cannot hold" in message


def test_selection_error_renders_as_a_cli_error_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI funnel prints the selection error as its `error:` line and exits 1, not a traceback."""
    from dhis2w_core.v43.plugins.metadata.service import MetadataSelectionError

    app = typer.Typer(pretty_exceptions_enable=False)

    @app.command()
    def boom() -> None:
        raise MetadataSelectionError(
            "listing dataSets: the selection `organisationUnits~size` returns a scalar "
            "the DataSet model cannot hold; ask for a selection it can hold, for example `id,name`"
        )

    monkeypatch.setattr(sys, "argv", ["d2w"])
    with pytest.raises(SystemExit) as exit_info:
        run_app(app)

    assert exit_info.value.code == 1
    rendered = capsys.readouterr()
    assert "error: listing dataSets: the selection `organisationUnits~size`" in rendered.err
    assert "Traceback" not in rendered.err + rendered.out


@respx.mock
def test_cli_lists_a_size_transform_as_json_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`d2w -j metadata list --fields '...~size'` prints the rows, on every version tree."""
    monkeypatch.setenv("DHIS2_VERSION", core_version)
    mock_system_info(core_version)
    respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=_page([{"id": "DSancMonth1", "name": "ANC monthly", "organisationUnits": 1096}]),
    )

    result = CliRunner().invoke(
        build_app(),
        ["-j", "metadata", "list", "dataSets", "--fields", _SIZE_SELECTION],
    )

    assert result.exit_code == 0, result.output
    assert '"organisationUnits": 1096' in result.output


@respx.mock
def test_cli_table_reads_the_transformed_column_parity(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Rich table fills the `~size` column from the key DHIS2 answers under, on every tree."""
    monkeypatch.setenv("DHIS2_VERSION", core_version)
    mock_system_info(core_version)
    respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=_page([{"id": "DSancMonth1", "name": "ANC monthly", "organisationUnits": 1096}]),
    )

    result = CliRunner().invoke(
        build_app(),
        ["metadata", "list", "dataSets", "--fields", _SIZE_SELECTION],
    )

    assert result.exit_code == 0, result.output
    assert "1096" in result.output
    assert "WARNING: --fields not in the generated" not in result.output
