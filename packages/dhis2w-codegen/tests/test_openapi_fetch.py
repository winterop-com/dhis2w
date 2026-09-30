"""Unit tests for capturing the live OpenAPI document into the generated tree."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from dhis2w_client import BasicAuth
from dhis2w_codegen.discover import version_key_from_raw
from dhis2w_codegen.openapi_fetch import fetch_openapi

_BASE_URL = "http://dhis2.test"
_DOCUMENT = b'{\n  "openapi":"3.0.0",\n  "paths":{}\n}'


@pytest.mark.parametrize(
    ("raw_version", "expected"),
    [("2.41.10", "v41"), ("2.43.1", "v43"), ("2.44-SNAPSHOT", "v44")],
)
def test_version_key_from_raw(raw_version: str, expected: str) -> None:
    """Release and snapshot version strings map to their tree key."""
    assert version_key_from_raw(raw_version) == expected


@respx.mock
async def test_fetch_openapi_writes_bytes_verbatim(tmp_path: Path) -> None:
    """The document lands byte-for-byte under the key the server reports, and a re-fetch reports unchanged."""
    respx.get(f"{_BASE_URL}/api/system/info").mock(return_value=httpx.Response(200, json={"version": "2.44-SNAPSHOT"}))
    respx.get(f"{_BASE_URL}/api/openapi/openapi.json").mock(return_value=httpx.Response(200, content=_DOCUMENT))
    auth = BasicAuth(username="admin", password="district")

    first = await fetch_openapi(_BASE_URL, auth, tmp_path)
    second = await fetch_openapi(_BASE_URL, auth, tmp_path)

    assert first.version_key == "v44"
    assert first.path == tmp_path / "v44" / "openapi.json"
    assert first.path.read_bytes() == _DOCUMENT
    assert first.size_bytes == len(_DOCUMENT)
    assert first.changed is True
    assert second.changed is False
    assert second.openapi_sha256 == first.openapi_sha256


@respx.mock
async def test_fetch_openapi_rejects_non_json(tmp_path: Path) -> None:
    """A login page served with 200 is refused instead of being committed as the document."""
    respx.get(f"{_BASE_URL}/api/system/info").mock(return_value=httpx.Response(200, json={"version": "2.43.1"}))
    respx.get(f"{_BASE_URL}/api/openapi/openapi.json").mock(return_value=httpx.Response(200, content=b"<html>"))

    with pytest.raises(ValueError):
        await fetch_openapi(_BASE_URL, BasicAuth(username="admin", password="district"), tmp_path)
    assert not (tmp_path / "v43" / "openapi.json").exists()
