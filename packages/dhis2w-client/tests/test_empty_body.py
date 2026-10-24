"""An empty successful body is nothing for a write or a 204, and a refusal for a read (DHIS2_ISSUES.md #146)."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import cast

import httpx
import httpx2
import pytest
import respx
from dhis2w_client import BasicAuth, Dhis2ApiError, Dhis2Client

TREES = ["v41", "v42", "v43", "v44"]


def _answer(method: str, status: int, content: bytes = b"") -> httpx2.Response:
    """Build a response to one request, the way the transport hands it to the client."""
    return httpx2.Response(status, content=content, request=httpx2.Request(method, "https://dhis2.example/api/x"))


def _parse(tree: str) -> Callable[[httpx2.Response], object]:
    """Reach one version tree's body parser."""
    parser = importlib.import_module(f"dhis2w_client.{tree}.client").Dhis2Client._parse_json
    return cast("Callable[[httpx2.Response], object]", parser)


@pytest.mark.parametrize("tree", TREES)
def test_a_read_answered_with_nothing_is_an_error(tree: str) -> None:
    """A GET 200 with no body is how DHIS2 2.42 refuses an export outside the account's scope."""
    with pytest.raises(Dhis2ApiError) as raised:
        _parse(tree)(_answer("GET", 200))
    assert raised.value.status_code == 200
    assert "empty body" in raised.value.message


@pytest.mark.parametrize("tree", TREES)
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_write_answered_with_nothing_is_an_empty_document(tree: str, method: str) -> None:
    """DHIS2 answers many writes with no body, and that is a success with nothing to read."""
    assert _parse(tree)(_answer(method, 200)) == {}


@pytest.mark.parametrize("tree", TREES)
def test_a_204_read_is_an_empty_document(tree: str) -> None:
    """No Content says nothing is the answer, whatever the method."""
    assert _parse(tree)(_answer("GET", 204)) == {}


@pytest.mark.parametrize("tree", TREES)
def test_a_read_answered_with_a_document_is_that_document(tree: str) -> None:
    """The ordinary case is untouched."""
    assert _parse(tree)(_answer("GET", 200, b'{"dataSet": "pBOMPrpg1QX", "dataValues": []}')) == {
        "dataSet": "pBOMPrpg1QX",
        "dataValues": [],
    }


@respx.mock
async def test_an_export_answered_with_nothing_raises_rather_than_returning_an_empty_set(
    server_version: str, mock_system_info: Callable[..., None]
) -> None:
    """The refused export does not come back as an empty `DataValueSet` on any version."""
    mock_system_info(server_version)
    respx.get("https://dhis2.example/api/dataValueSets").mock(return_value=httpx.Response(200, content=b""))
    client = Dhis2Client("https://dhis2.example", auth=BasicAuth(username="a", password="b"))
    try:
        await client.connect()
        with pytest.raises(Dhis2ApiError):
            await client.data_values.export(data_set="pBOMPrpg1QX", period="202507", org_unit="ImspTQPwCqd")
    finally:
        await client.close()
