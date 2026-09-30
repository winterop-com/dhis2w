"""Generated Indicator model for DHIS2 v44. Do not edit by hand."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..common import Reference
from ..enums import AggregationType, DimensionItemType


class Indicator(BaseModel):
    """Generated model for DHIS2 `Indicator`.

    DHIS2 Indicator - persisted metadata (generated from /api/schemas at DHIS2 v44).

    API endpoint: /api/indicators.

    Field `Field(description=...)` entries flag DHIS2 semantics the bare
    type can't capture: which side of a relationship owns the link
    (writable) vs the inverse side (ignored by the API), uniqueness
    constraints, and length bounds.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    access: Any | None = Field(default=None, description="Reference to Access. Read-only (inverse side).")
    aggregateExportAttributeOptionCombo: str | None = Field(default=None, description="Length/value max=255.")
    aggregateExportCategoryOptionCombo: str | None = Field(default=None, description="Length/value max=255.")
    aggregationType: AggregationType | None = None
    annualized: bool | None = None
    attributeValues: Any | None = Field(default=None, description="Reference to AttributeValues.")
    code: str | None = Field(default=None, description="Unique. Length/value max=50.")
    created: datetime | None = None
    createdBy: Reference | None = Field(default=None, description="Reference to User.")
    dataSets: list[Any] | None = Field(default=None, description="Collection of DataSet. Read-only (inverse side).")
    decimals: int | None = Field(default=None, description="Length/value max=2147483647.")
    denominator: str | None = Field(default=None, description="Length/value max=2147483647.")
    denominatorDescription: str | None = Field(default=None, description="Length/value max=2147483647.")
    description: str | None = Field(default=None, description="Length/value min=1, max=2147483647.")
    dimensionItem: str | None = Field(default=None, description="Read-only.")
    dimensionItemType: DimensionItemType | None = None
    displayDenominatorDescription: str | None = Field(default=None, description="Read-only.")
    displayDescription: str | None = Field(default=None, description="Read-only.")
    displayFormName: str | None = Field(default=None, description="Read-only.")
    displayName: str | None = Field(default=None, description="Read-only.")
    displayNumeratorDescription: str | None = Field(default=None, description="Read-only.")
    displayShortName: str | None = Field(default=None, description="Read-only.")
    explodedDenominator: str | None = Field(default=None, description="Length/value max=2147483647.")
    explodedNumerator: str | None = Field(default=None, description="Length/value max=2147483647.")
    formName: str | None = Field(default=None, description="Length/value max=2147483647.")
    href: str | None = None
    id: str | None = Field(default=None, description="Unique. Length/value min=11, max=11.")
    indicatorGroups: list[Any] | None = Field(
        default=None, description="Collection of IndicatorGroup. Read-only (inverse side)."
    )
    indicatorType: Reference | None = Field(default=None, description="Reference to IndicatorType.")
    lastUpdated: datetime | None = None
    lastUpdatedBy: Reference | None = Field(default=None, description="Reference to User.")
    legendSet: Reference | None = Field(default=None, description="Reference to LegendSet. Read-only (inverse side).")
    legendSets: list[Any] | None = Field(default=None, description="Collection of LegendSet.")
    name: str | None = Field(default=None, description="Length/value min=1, max=230.")
    numerator: str | None = Field(default=None, description="Length/value max=2147483647.")
    numeratorDescription: str | None = Field(default=None, description="Length/value max=2147483647.")
    queryMods: Any | None = Field(default=None, description="Reference to QueryModifiers. Read-only (inverse side).")
    sharing: Any | None = Field(default=None, description="Reference to Sharing.")
    shortName: str | None = Field(default=None, description="Length/value min=1, max=50.")
    style: Any | None = Field(default=None, description="Reference to ObjectStyle.")
    translations: list[Any] | None = Field(default=None, description="Collection of Translation.")
    url: str | None = Field(default=None, description="Length/value max=255.")
    user: Reference | None = Field(default=None, description="Reference to User. Read-only (inverse side).")
