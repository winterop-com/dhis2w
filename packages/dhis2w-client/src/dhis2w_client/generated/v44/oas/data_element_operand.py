"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict

from ._enums import AggregationType, DimensionItemType

if TYPE_CHECKING:
    from .identifiable_object import IdentifiableObject
    from .query_modifiers import QueryModifiers


class DataElementOperand(_BaseModel):
    """OpenAPI schema `DataElementOperand`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    aggregationType: AggregationType | None = None
    attributeOptionCombo: IdentifiableObject | None = None
    categoryOptionCombo: IdentifiableObject | None = None
    dataElement: IdentifiableObject | None = None
    dimensionItem: str | None = None
    dimensionItemType: DimensionItemType | None = None
    displayFormName: str | None = None
    displayName: str | None = None
    displayShortName: str | None = None
    id: str | None = None
    name: str | None = None
    queryMods: QueryModifiers | None = None
    shortName: str | None = None
