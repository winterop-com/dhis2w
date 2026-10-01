"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict

from ._enums import EventStatus

if TYPE_CHECKING:
    from .access import Access
    from .attribute_values import AttributeValues
    from .event_data_value import EventDataValue
    from .relationship_item_params import RelationshipItemParams
    from .sharing import Sharing
    from .translation import Translation
    from .user_info_snapshot import UserInfoSnapshot


class TrackerEventParamsAssignedUser(_BaseModel):
    """OpenAPI schema `TrackerEventParamsAssignedUser`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParamsAttributeOptionCombo(_BaseModel):
    """OpenAPI schema `TrackerEventParamsAttributeOptionCombo`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParamsCreatedBy(_BaseModel):
    """OpenAPI schema `TrackerEventParamsCreatedBy`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParamsEnrollment(_BaseModel):
    """OpenAPI schema `TrackerEventParamsEnrollment`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParamsLastUpdatedBy(_BaseModel):
    """OpenAPI schema `TrackerEventParamsLastUpdatedBy`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParamsNotes(_BaseModel):
    """OpenAPI schema `TrackerEventParamsNotes`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParamsOrganisationUnit(_BaseModel):
    """OpenAPI schema `TrackerEventParamsOrganisationUnit`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParamsProgramStage(_BaseModel):
    """OpenAPI schema `TrackerEventParamsProgramStage`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParamsUser(_BaseModel):
    """OpenAPI schema `TrackerEventParamsUser`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackerEventParams(_BaseModel):
    """OpenAPI schema `TrackerEventParams`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    access: Access | None = None
    assignedUser: TrackerEventParamsAssignedUser | None = None
    attributeOptionCombo: TrackerEventParamsAttributeOptionCombo | None = None
    attributeValues: AttributeValues | None = None
    code: str | None = None
    completedBy: str | None = None
    completedDate: datetime | None = None
    creatableInSearchScope: bool | None = None
    created: datetime | None = None
    createdAtClient: datetime | None = None
    createdBy: TrackerEventParamsCreatedBy | None = None
    createdByUserInfo: UserInfoSnapshot | None = None
    deleted: bool | None = None
    displayName: str | None = None
    enrollment: TrackerEventParamsEnrollment | None = None
    eventDataValues: list[EventDataValue] | None = None
    geometry: dict[str, Any] | None = None
    href: str | None = None
    id: int | None = None
    lastSynchronized: datetime | None = None
    lastUpdated: datetime | None = None
    lastUpdatedAtClient: datetime | None = None
    lastUpdatedBy: TrackerEventParamsLastUpdatedBy | None = None
    lastUpdatedByUserInfo: UserInfoSnapshot | None = None
    name: str | None = None
    notes: list[TrackerEventParamsNotes] | None = None
    occurredDate: datetime | None = None
    organisationUnit: TrackerEventParamsOrganisationUnit | None = None
    owner: str | None = None
    programStage: TrackerEventParamsProgramStage | None = None
    relationshipItems: list[RelationshipItemParams] | None = None
    scheduledDate: datetime | None = None
    sharing: Sharing | None = None
    status: EventStatus | None = None
    translations: list[Translation] | None = None
    uID: str | None = None
    uid: str | None = None
    user: TrackerEventParamsUser | None = None
