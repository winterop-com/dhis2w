"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict


class CacheRule(_BaseModel):
    """OpenAPI schema `CacheRule`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    immutable: bool | None = None
    maxAgeSeconds: int | None = None
    mustRevalidate: bool | None = None
    pattern: str | None = None
