"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict

from ._enums import AggregationType, DimensionItemType

if TYPE_CHECKING:
    from .category_option_combo_params import CategoryOptionComboParams
    from .data_element_params import DataElementParams
    from .query_modifiers import QueryModifiers


class DataElementOperandParams(_BaseModel):
    """OpenAPI schema `DataElementOperandParams`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    aggregationType: AggregationType | None = None
    attributeOptionCombo: CategoryOptionComboParams | None = None
    categoryOptionCombo: CategoryOptionComboParams | None = None
    dataElement: DataElementParams | None = None
    dimensionItem: str | None = None
    dimensionItemType: DimensionItemType | None = None
    displayFormName: str | None = None
    displayName: str | None = None
    displayShortName: str | None = None
    id: str | None = None
    name: str | None = None
    queryMods: QueryModifiers | None = None
    shortName: str | None = None
