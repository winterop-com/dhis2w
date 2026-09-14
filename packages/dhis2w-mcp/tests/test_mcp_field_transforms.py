"""`metadata_list` over MCP answers a field-transformer selection the way the CLI does.

The tool calls the same service as `d2w metadata list`, so `organisationUnits~size` returns the
transformed row DHIS2 sent, and a page the model cannot hold comes back as a `ToolError` naming the
selection rather than a validation traceback. Parametrised over v41 / v42 / v43. Mocked (respx).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
import respx
from dhis2w_mcp.server import build_server
from fastmcp import Client
from fastmcp.exceptions import ToolError

_HOST = "https://dhis2.example"

_SIZE_SELECTION = "id,name,organisationUnits~size"


@respx.mock
async def test_metadata_list_returns_a_transformed_row(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool returns the `~size` count as DHIS2 answered it, on every version tree."""
    monkeypatch.setenv("DHIS2_VERSION", core_version)
    mock_system_info(core_version)
    respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=httpx.Response(
            200,
            json={"dataSets": [{"id": "DSancMonth1", "name": "ANC monthly", "organisationUnits": 1096}]},
        ),
    )

    async with Client(build_server()) as client:
        result = await client.call_tool("metadata_list", {"resource": "dataSets", "fields": _SIZE_SELECTION})

    assert result.structured_content == {
        "result": [{"id": "DSancMonth1", "name": "ANC monthly", "organisationUnits": 1096}]
    }


@respx.mock
async def test_metadata_list_names_the_selection_it_cannot_hold(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page the generated model cannot hold reaches the client as an actionable tool error."""
    monkeypatch.setenv("DHIS2_VERSION", core_version)
    mock_system_info(core_version)
    respx.get(f"{_HOST}/api/dataSets").mock(
        return_value=httpx.Response(200, json={"dataSets": [{"id": "DSancMonth1", "organisationUnits": 1096}]}),
    )

    async with Client(build_server()) as client:
        with pytest.raises(ToolError) as failure:
            await client.call_tool("metadata_list", {"resource": "dataSets", "fields": "id,organisationUnits"})

    message = str(failure.value)
    assert "listing dataSets" in message
    assert "the DataSet model cannot hold" in message
