"""open_client threads max_response_bytes and deadline through to the client it opens."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import httpx
import pytest
import respx
from dhis2w_client import Dhis2Client
from dhis2w_client.errors import RequestDeadlineError, ResponseTooLargeError
from dhis2w_core.profile import Profile, bind_version_tree

MODULES = [
    "dhis2w_core.client_context",
    "dhis2w_core.v41.client_context",
    "dhis2w_core.v42.client_context",
    "dhis2w_core.v43.client_context",
    "dhis2w_core.v44.client_context",
]

BASE_URL = "http://mocked.limits.example"

OpenClient = Callable[..., AbstractAsyncContextManager[Dhis2Client]]


@pytest.fixture(autouse=True)
def _reset_bound_tree() -> AsyncIterator[None] | Any:
    """Clear any bound version tree around each test so process-wide state cannot leak."""
    bind_version_tree(None)
    yield None
    bind_version_tree(None)


def _open_client(module: str) -> OpenClient:
    """Return the `open_client` one tree defines."""
    opener: OpenClient = importlib.import_module(module).open_client
    return opener


def _profile() -> Profile:
    """A PAT profile against the mocked instance."""
    return Profile(base_url=BASE_URL, auth="pat", token="d2pat_x")


@pytest.mark.parametrize("module", MODULES)
@respx.mock
async def test_max_response_bytes_reaches_the_client(module: str) -> None:
    """An answer past `max_response_bytes` is refused on the version probe `connect()` makes."""
    respx.get(f"{BASE_URL}/").mock(return_value=httpx.Response(200, text=""))
    respx.get(f"{BASE_URL}/api/system/info").mock(
        return_value=httpx.Response(200, json={"version": "2.43.0", "revision": "x" * 4096}),
    )
    with pytest.raises(ResponseTooLargeError):
        async with _open_client(module)(_profile(), system_cache_ttl=None, max_response_bytes=1024):
            pass


@pytest.mark.parametrize("module", MODULES)
@respx.mock
async def test_deadline_reaches_the_client(module: str) -> None:
    """A request slower than `deadline` raises `RequestDeadlineError` on the version probe."""

    async def slow(request: httpx.Request) -> httpx.Response:
        """Answer only after the deadline has passed."""
        await asyncio.sleep(2.0)
        return httpx.Response(200, json={"version": "2.43.0"})

    respx.get(f"{BASE_URL}/").mock(return_value=httpx.Response(200, text=""))
    respx.get(f"{BASE_URL}/api/system/info").mock(side_effect=slow)
    with pytest.raises(RequestDeadlineError):
        async with _open_client(module)(_profile(), system_cache_ttl=None, deadline=0.2):
            pass


@pytest.mark.parametrize("module", MODULES)
@respx.mock
async def test_no_limit_by_default(module: str) -> None:
    """Without either argument an answer of any size and pace is read as it always is."""
    respx.get(f"{BASE_URL}/").mock(return_value=httpx.Response(200, text=""))
    respx.get(f"{BASE_URL}/api/system/info").mock(
        return_value=httpx.Response(200, json={"version": "2.43.0", "revision": "x" * 4096}),
    )
    async with _open_client(module)(_profile(), system_cache_ttl=None) as client:
        assert client.version_key == "v43"
