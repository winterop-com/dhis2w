"""Capture a live DHIS2 `/api/openapi/openapi.json` into `generated/v{N}/openapi.json`."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx2
from dhis2w_client import AuthProvider
from pydantic import BaseModel, ConfigDict

from dhis2w_codegen.discover import version_key_from_raw

_OPENAPI_PATH = "/api/openapi/openapi.json"


class OpenApiCapture(BaseModel):
    """Result of capturing one live OpenAPI document."""

    model_config = ConfigDict(frozen=True)

    raw_version: str
    version_key: str
    path: Path
    size_bytes: int
    openapi_sha256: str
    changed: bool


async def fetch_openapi(url: str, auth: AuthProvider, output_root: Path) -> OpenApiCapture:
    """Download the OpenAPI document and write it verbatim to `<output_root>/v{N}/openapi.json`.

    The bytes are stored exactly as the server sent them, so `openapi_sha256` in
    `openapi_manifest.json` fingerprints the live document rather than a reformatted copy.
    """
    headers = await auth.headers()
    async with httpx2.AsyncClient(
        base_url=url.rstrip("/"),
        headers=headers,
        timeout=httpx2.Timeout(300.0, connect=60.0),
    ) as http:
        info_response = await http.get("/api/system/info")
        info_response.raise_for_status()
        raw_version = str(info_response.json().get("version", ""))
        document_response = await http.get(_OPENAPI_PATH)
        document_response.raise_for_status()
    body = document_response.content
    json.loads(body)
    version_key = version_key_from_raw(raw_version)
    destination = output_root / version_key / "openapi.json"
    previous = destination.read_bytes() if destination.exists() else None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    return OpenApiCapture(
        raw_version=raw_version,
        version_key=version_key,
        path=destination,
        size_bytes=len(body),
        openapi_sha256=hashlib.sha256(body).hexdigest(),
        changed=previous != body,
    )
