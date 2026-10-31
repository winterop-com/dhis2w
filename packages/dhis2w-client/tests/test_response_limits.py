"""The limits on what one answer may cost: its decoded size and its time, against a hostile loopback server."""

from __future__ import annotations

import asyncio
import gzip
import importlib
import json
import time
import tracemalloc
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from dhis2w_client import BasicAuth, Dhis2ApiError, Dhis2Client, RequestDeadlineError, ResponseTooLargeError

MIB = 1024 * 1024

#: Every tree's client, since each carries its own copy of the request path.
CLIENTS = [
    pytest.param(importlib.import_module(f"dhis2w_client.v{major}.client").Dhis2Client, id=f"v{major}")
    for major in (41, 42, 43, 44)
]

Handler = Callable[[asyncio.StreamWriter], Awaitable[None]]


def _bomb(decoded_bytes: int) -> bytes:
    """A JSON object of about that many decoded bytes, gzipped twice: a few hundred bytes on the wire."""
    document = json.dumps({"version": "2.43.0", "pad": "x" * decoded_bytes}).encode()
    return gzip.compress(gzip.compress(document))


def _answer(status: str, body: bytes, *headers: str) -> Handler:
    """A handler that writes one complete answer."""

    async def write(writer: asyncio.StreamWriter) -> None:
        head = [f"HTTP/1.1 {status}", f"Content-Length: {len(body)}", "Connection: close", *headers]
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + body)
        await writer.drain()

    return write


def _chunked(status: str, pieces: list[bytes]) -> Handler:
    """A handler that writes an answer with no Content-Length, one chunk per piece."""

    async def write(writer: asyncio.StreamWriter) -> None:
        writer.write(f"HTTP/1.1 {status}\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n".encode())
        for piece in pieces:
            writer.write(b"%x\r\n%s\r\n" % (len(piece), piece))
            await writer.drain()
        writer.write(b"0\r\n\r\n")
        await writer.drain()

    return write


async def _drip(writer: asyncio.StreamWriter) -> None:
    """A handler that never finishes its body, sending a byte well inside any read timeout."""
    writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
    while True:
        writer.write(b"1\r\nx\r\n")
        await writer.drain()
        await asyncio.sleep(0.01)


async def _silent(writer: asyncio.StreamWriter) -> None:
    """A handler that takes the request and never answers."""
    await asyncio.Event().wait()


class Hostile:
    """A loopback server answering each path with its handler, recording what it was asked."""

    def __init__(self) -> None:
        """Start with nothing scripted."""
        self.handlers: dict[str, Handler] = {}
        self.asked: list[str] = []
        self.url = ""

    def on(self, path: str, handler: Handler) -> None:
        """Answer this path with this handler."""
        self.handlers[path] = handler

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Answer one request and close."""
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            path = head.split(b" ", 2)[1].decode().split("?")[0]
            self.asked.append(path)
            await self.handlers[path](writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


@pytest_asyncio.fixture
async def hostile() -> AsyncIterator[Hostile]:
    """A hostile server on an ephemeral loopback port."""
    server = Hostile()
    listening = await asyncio.start_server(server.handle, "127.0.0.1", 0)
    server.url = f"http://127.0.0.1:{listening.sockets[0].getsockname()[1]}"
    try:
        yield server
    finally:
        listening.close()


def _connected(client_class: Any, url: str, **limits: Any) -> Any:
    """A client that skips the probes, so a test drives one request at a time."""
    return client_class(url, auth=BasicAuth(username="u", password="p"), skip_version_probe=True, **limits)


async def _peak_while(call: Awaitable[Any]) -> tuple[Any, int]:
    """Await the call and say the most Python memory it held at once."""
    tracemalloc.start()
    try:
        result = await call
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("client_class", CLIENTS)
async def test_a_double_gzip_answer_is_refused_as_it_decodes(hostile: Hostile, client_class: Any) -> None:
    hostile.on("/api/x", _answer("200 OK", _bomb(8 * MIB), "Content-Encoding: gzip, gzip"))
    async with _connected(client_class, hostile.url, max_response_bytes=MIB) as client:
        tracemalloc.start()
        try:
            with pytest.raises(ResponseTooLargeError) as refused:
                await client.get_raw("/api/x")
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    assert refused.value.limit == MIB
    assert "/api/x" in str(refused.value)
    assert peak < 4 * MIB


@pytest.mark.parametrize("client_class", CLIENTS)
async def test_a_chunked_answer_with_no_length_is_counted(hostile: Hostile, client_class: Any) -> None:
    hostile.on("/api/x", _chunked("200 OK", [b"x" * MIB] * 3))
    async with _connected(client_class, hostile.url, max_response_bytes=MIB) as client:
        with pytest.raises(ResponseTooLargeError):
            await client.get_raw("/api/x")


async def test_a_refused_error_body_is_refused_too(hostile: Hostile) -> None:
    hostile.on("/api/x", _answer("500 Oops", _bomb(8 * MIB), "Content-Encoding: gzip, gzip"))
    async with _connected(Dhis2Client, hostile.url, max_response_bytes=MIB) as client:
        with pytest.raises(ResponseTooLargeError):
            await client.get_raw("/api/x")


async def test_a_streamed_error_body_is_capped_and_a_streamed_body_is_not(hostile: Hostile) -> None:
    written: list[bytes] = []
    hostile.on("/api/ok", _chunked("200 OK", [b"x" * MIB] * 3))
    hostile.on("/api/bad", _answer("500 Oops", _bomb(8 * MIB), "Content-Encoding: gzip, gzip"))
    async with _connected(Dhis2Client, hostile.url, max_response_bytes=MIB) as client:
        assert await client.stream("GET", "/api/ok", written.append) == 3 * MIB
        with pytest.raises(ResponseTooLargeError):
            await client.stream("GET", "/api/bad", written.append)


@pytest.mark.parametrize("client_class", CLIENTS)
async def test_an_answer_within_the_limit_reads_as_it_always_did(hostile: Hostile, client_class: Any) -> None:
    body = gzip.compress(json.dumps({"version": "2.43.0"}).encode())
    hostile.on("/api/x", _answer("200 OK", body, "Content-Encoding: gzip", "Content-Type: application/json"))
    hostile.on("/api/bad", _answer("409 Conflict", b'{"message": "no"}', "Content-Type: application/json"))
    async with _connected(client_class, hostile.url, max_response_bytes=MIB) as client:
        assert await client.get_raw("/api/x") == {"version": "2.43.0"}
        response = await client.get_response("/api/x")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert "content-encoding" not in response.headers
        assert response.request.method == "GET"
        with pytest.raises(Dhis2ApiError) as refused:
            await client.get_raw("/api/bad")
    assert refused.value.status_code == 409
    assert refused.value.message == "Conflict"


async def test_an_answer_already_read_by_a_mock_transport_is_read_under_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = httpx2.AsyncClient
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json={"ok": True}))
    monkeypatch.setattr(httpx2, "AsyncClient", lambda **kwargs: real(transport=transport, **kwargs))
    async with _connected(Dhis2Client, "https://dhis2.example", max_response_bytes=MIB) as client:
        assert await client.get_raw("/api/x") == {"ok": True}


async def test_an_answer_read_under_the_limit_says_how_long_it_took(hostile: Hostile) -> None:
    hostile.on("/api/x", _answer("200 OK", b"{}"))
    async with _connected(Dhis2Client, hostile.url, max_response_bytes=MIB) as client:
        assert (await client.get_response("/api/x")).elapsed.total_seconds() >= 0


async def test_an_answer_of_exactly_the_limit_is_read(hostile: Hostile) -> None:
    hostile.on("/api/x", _chunked("200 OK", [b"x" * 1024]))
    async with _connected(Dhis2Client, hostile.url, max_response_bytes=1024) as client:
        assert len((await client.get_response("/api/x")).content) == 1024


async def test_no_limit_reads_the_whole_answer(hostile: Hostile) -> None:
    hostile.on("/api/x", _chunked("200 OK", [b"x" * MIB] * 3))
    async with _connected(Dhis2Client, hostile.url) as client:
        assert len((await client.get_response("/api/x")).content) == 3 * MIB


@pytest.mark.parametrize("client_class", CLIENTS)
async def test_the_version_probe_is_held_to_the_limit(hostile: Hostile, client_class: Any) -> None:
    hostile.on("/", _answer("200 OK", b"<html></html>"))
    hostile.on("/api/system/info", _answer("200 OK", _bomb(8 * MIB), "Content-Encoding: gzip, gzip"))
    client = client_class(hostile.url, auth=BasicAuth(username="u", password="p"), max_response_bytes=MIB)
    with pytest.raises(ResponseTooLargeError):
        await client.connect()


@pytest.mark.parametrize("client_class", CLIENTS)
async def test_the_canonical_url_probe_never_reads_a_body(hostile: Hostile, client_class: Any) -> None:
    hostile.on("/", _answer("200 OK", _bomb(8 * MIB), "Content-Encoding: gzip, gzip"))
    resolved, peak = await _peak_while(client_class._resolve_canonical_base_url(hostile.url))
    assert resolved == hostile.url
    assert peak < 2 * MIB


async def test_the_canonical_url_probe_never_reads_a_redirect_body(hostile: Hostile) -> None:
    location = f"Location: {hostile.url}/next/"
    hostile.on("/", _answer("302 Found", _bomb(8 * MIB), "Content-Encoding: gzip, gzip", location))
    hostile.on("/next/", _answer("200 OK", b"<html></html>"))
    resolved, peak = await _peak_while(Dhis2Client._resolve_canonical_base_url(hostile.url))
    assert resolved == f"{hostile.url}/next"
    assert hostile.asked == ["/", "/next/"]
    assert peak < 2 * MIB


async def test_the_canonical_url_probe_stops_at_a_redirect_loop(hostile: Hostile) -> None:
    hostile.on("/", _answer("302 Found", b"", f"Location: {hostile.url}/"))
    assert await Dhis2Client._resolve_canonical_base_url(hostile.url) == hostile.url
    assert len(hostile.asked) == 20


@pytest.mark.parametrize("client_class", CLIENTS)
async def test_the_shape_probe_refuses_an_answer_past_its_cap(hostile: Hostile, client_class: Any) -> None:
    hostile.on("/api/system/info", _answer("200 OK", _bomb(8 * MIB), "Content-Encoding: gzip, gzip"))
    looks_like_dhis2, peak = await _peak_while(client_class._probe_looks_like_dhis2(hostile.url))
    assert looks_like_dhis2 is False
    assert peak < 4 * MIB


@pytest.mark.parametrize("client_class", CLIENTS)
async def test_a_drip_is_cut_at_the_deadline(hostile: Hostile, client_class: Any) -> None:
    hostile.on("/api/x", _drip)
    started = time.monotonic()
    async with _connected(client_class, hostile.url, deadline=0.2, timeout=1.0) as client:
        async with asyncio.timeout(10):
            with pytest.raises(RequestDeadlineError) as refused:
                await client.get_raw("/api/x")
    assert time.monotonic() - started < 5
    assert isinstance(refused.value, TimeoutError)
    assert "/api/x" in str(refused.value)


async def test_a_drip_is_cut_at_the_deadline_with_a_limit_set(hostile: Hostile) -> None:
    hostile.on("/api/x", _drip)
    async with _connected(Dhis2Client, hostile.url, deadline=0.2, timeout=1.0, max_response_bytes=MIB) as client:
        async with asyncio.timeout(10):
            with pytest.raises(RequestDeadlineError):
                await client.get_raw("/api/x")


async def test_the_deadline_is_not_taken_for_any_other_timeout(hostile: Hostile) -> None:
    hostile.on("/api/x", _silent)
    async with _connected(Dhis2Client, hostile.url, deadline=30.0, timeout=0.1) as client:
        with pytest.raises(Exception) as refused:
            await client.get_raw("/api/x")
    assert not isinstance(refused.value, RequestDeadlineError)


async def test_the_probes_fall_back_at_the_deadline(hostile: Hostile) -> None:
    hostile.on("/", _silent)
    hostile.on("/api/system/info", _silent)
    started = time.monotonic()
    assert await Dhis2Client._resolve_canonical_base_url(hostile.url, deadline=0.1) == hostile.url
    assert await Dhis2Client._probe_looks_like_dhis2(hostile.url, deadline=0.1) is False
    assert time.monotonic() - started < 3
