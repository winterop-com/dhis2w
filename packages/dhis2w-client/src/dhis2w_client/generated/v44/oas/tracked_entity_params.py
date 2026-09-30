"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict

if TYPE_CHECKING:
    from .access import Access
    from .attribute_values import AttributeValues
    from .relationship_item_params import RelationshipItemParams
    from .sharing import Sharing
    from .tracked_entity_attribute_value_params import TrackedEntityAttributeValueParams
    from .tracked_entity_program_owner_params import TrackedEntityProgramOwnerParams
    from .translation import Translation
    from .user_info_snapshot import UserInfoSnapshot


class TrackedEntityParamsCreatedBy(_BaseModel):
    """OpenAPI schema `TrackedEntityParamsCreatedBy`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackedEntityParamsEnrollments(_BaseModel):
    """OpenAPI schema `TrackedEntityParamsEnrollments`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackedEntityParamsLastUpdatedBy(_BaseModel):
    """OpenAPI schema `TrackedEntityParamsLastUpdatedBy`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackedEntityParamsOrganisationUnit(_BaseModel):
    """OpenAPI schema `TrackedEntityParamsOrganisationUnit`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackedEntityParamsTrackedEntityType(_BaseModel):
    """OpenAPI schema `TrackedEntityParamsTrackedEntityType`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackedEntityParamsUser(_BaseModel):
    """OpenAPI schema `TrackedEntityParamsUser`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    id: str | None = None


class TrackedEntityParams(_BaseModel):
    """OpenAPI schema `TrackedEntityParams`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    access: Access | None = None
    attributeValues: AttributeValues | None = None
    code: str | None = None
    created: datetime | None = None
    createdAtClient: datetime | None = None
    createdBy: TrackedEntityParamsCreatedBy | None = None
    createdByUserInfo: UserInfoSnapshot | None = None
    deleted: bool | None = None
    displayName: str | None = None
    enrollments: list[TrackedEntityParamsEnrollments] | None = None
    geometry: dict[str, Any] | None = None
    href: str | None = None
    id: int | None = None
    inactive: bool | None = None
    lastSynchronized: datetime | None = None
    lastUpdated: datetime | None = None
    lastUpdatedAtClient: datetime | None = None
    lastUpdatedBy: TrackedEntityParamsLastUpdatedBy | None = None
    lastUpdatedByUserInfo: UserInfoSnapshot | None = None
    name: str | None = None
    organisationUnit: TrackedEntityParamsOrganisationUnit | None = None
    owner: str | None = None
    potentialDuplicate: bool | None = None
    programOwners: list[TrackedEntityProgramOwnerParams] | None = None
    relationshipItems: list[RelationshipItemParams] | None = None
    sharing: Sharing | None = None
    trackedEntityAttributeValues: list[TrackedEntityAttributeValueParams] | None = None
    trackedEntityType: TrackedEntityParamsTrackedEntityType | None = None
    translations: list[Translation] | None = None
    uID: str | None = None
    uid: str | None = None
    user: TrackedEntityParamsUser | None = None
