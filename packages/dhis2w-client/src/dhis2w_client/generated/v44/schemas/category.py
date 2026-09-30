"""Generated Category model for DHIS2 v44. Do not edit by hand."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..common import Reference
from ..enums import AggregationType, DataDimensionType, ValueType


class Category(BaseModel):
    """Generated model for DHIS2 `Category`.

    DHIS2 Category - persisted metadata (generated from /api/schemas at DHIS2 v44).

    API endpoint: /api/categories.

    Field `Field(description=...)` entries flag DHIS2 semantics the bare
    type can't capture: which side of a relationship owns the link
    (writable) vs the inverse side (ignored by the API), uniqueness
    constraints, and length bounds.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    access: Any | None = Field(default=None, description="Reference to Access. Read-only (inverse side).")
    aggregationType: AggregationType | None = None
    allItems: bool | None = None
    attributeValues: Any | None = Field(default=None, description="Reference to AttributeValues.")
    categoryCombos: list[Any] | None = Field(
        default=None, description="Collection of CategoryCombo. Read-only (inverse side)."
    )
    categoryOptions: list[Any] | None = Field(default=None, description="Collection of CategoryOption.")
    code: str | None = Field(default=None, description="Unique. Length/value max=50.")
    created: datetime | None = None
    createdBy: Reference | None = Field(default=None, description="Reference to User.")
    dataDimension: bool | None = None
    dataDimensionType: DataDimensionType | None = None
    description: str | None = Field(default=None, description="Length/value max=2147483647.")
    dimension: str | None = Field(default=None, description="Read-only.")
    dimensionItemKeywords: Any | None = Field(
        default=None, description="Reference to DimensionItemKeywords. Read-only (inverse side)."
    )
    displayDescription: str | None = Field(default=None, description="Read-only.")
    displayName: str | None = Field(default=None, description="Read-only.")
    displayShortName: str | None = Field(default=None, description="Read-only.")
    filter: str | None = Field(default=None, description="Length/value max=2147483647.")
    href: str | None = Field(default=None, description="Length/value max=2147483647.")
    id: str | None = Field(default=None, description="Unique. Length/value min=11, max=11.")
    isDefault: bool | None = Field(default=None, description="Read-only.")
    items: list[Any] | None = Field(
        default=None, description="Collection of DimensionalItemObject. Read-only (inverse side)."
    )
    lastUpdated: datetime | None = None
    lastUpdatedBy: Reference | None = Field(default=None, description="Reference to User.")
    legendSet: Reference | None = Field(default=None, description="Reference to LegendSet. Read-only (inverse side).")
    name: str | None = Field(default=None, description="Unique. Length/value min=1, max=230.")
    optionSet: Reference | None = Field(default=None, description="Reference to OptionSet. Read-only (inverse side).")
    program: Reference | None = Field(default=None, description="Reference to Program. Read-only (inverse side).")
    programStage: Reference | None = Field(
        default=None, description="Reference to ProgramStage. Read-only (inverse side)."
    )
    repetition: Any | None = Field(default=None, description="Reference to EventRepetition. Read-only (inverse side).")
    sharing: Any | None = Field(default=None, description="Reference to Sharing.")
    shortName: str | None = Field(default=None, description="Unique. Length/value max=50.")
    translations: list[Any] | None = Field(default=None, description="Collection of Translation.")
    user: Reference | None = Field(default=None, description="Reference to User. Read-only (inverse side).")
    valueType: ValueType | None = None
