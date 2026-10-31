"""Reading a response under a size limit and a time limit -- shared across version trees.

`httpx2` decodes a compressed body in pieces of at most 1 MiB, however many encodings it
carries, so counting what `aiter_bytes` yields stops a small compressed answer before it
expands in memory.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator

import httpx2

from dhis2w_client.errors import RequestDeadlineError, ResponseTooLargeError


async def read_capped(response: httpx2.Response, limit: int, *, method: str, path: str) -> httpx2.Response:
    """Close a streamed `response` and return it read and decoded, refusing more than `limit` decoded bytes.

    The loop gets a turn after each decoded piece, so other tasks and a deadline keep running
    while a large body is read. The response returned holds the decoded body, so it no longer
    carries the headers that described the encoded one. A response a mock transport built read
    has no timing to carry over.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        async with contextlib.aclosing(response.aiter_bytes()) as decoded:
            async for chunk in decoded:
                total += len(chunk)
                if total > limit:
                    raise ResponseTooLargeError(method=method, path=path, limit=limit)
                chunks.append(chunk)
                await asyncio.sleep(0)
    finally:
        await response.aclose()
    headers = response.headers.copy()
    headers.pop("content-encoding", None)
    headers.pop("content-length", None)
    read = httpx2.Response(
        response.status_code,
        headers=headers,
        content=b"".join(chunks),
        request=response.request,
        extensions=response.extensions,
        history=response.history,
        default_encoding=response.default_encoding,
    )
    with contextlib.suppress(RuntimeError):
        read.elapsed = response.elapsed
    return read


@contextlib.asynccontextmanager
async def within_deadline(deadline: float | None, *, method: str, path: str) -> AsyncGenerator[None]:
    """Raise `RequestDeadlineError` when the body takes longer than `deadline` seconds; `None` sets no limit."""
    scope = asyncio.timeout(deadline)
    try:
        async with scope:
            yield
    except TimeoutError as error:
        if scope.expired():
            raise RequestDeadlineError(method=method, path=path, deadline=deadline) from error
        raise


__all__ = ["read_capped", "within_deadline"]
