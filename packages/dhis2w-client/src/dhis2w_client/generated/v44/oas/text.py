"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict


class Text(_BaseModel):
    """OpenAPI schema `Text`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    empty: bool | None = None
    numericInteger: bool | None = None
    specialDecimal: bool | None = None
    textualDecimal: bool | None = None
    textualInteger: bool | None = None
