"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict

if TYPE_CHECKING:
    from .category_option_group import CategoryOptionGroup
    from .identifiable_object import IdentifiableObject


class CategoryOptionGroupSetDimension(_BaseModel):
    """OpenAPI schema `CategoryOptionGroupSetDimension`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    categoryOptionGroupSet: IdentifiableObject | None = None
    categoryOptionGroups: list[CategoryOptionGroup] | None = None
