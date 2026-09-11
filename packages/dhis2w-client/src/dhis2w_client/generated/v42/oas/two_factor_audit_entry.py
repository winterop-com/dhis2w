"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict

from ._enums import TwoFactorType


class TwoFactorAuditEntry(_BaseModel):
    """OpenAPI schema `TwoFactorAuditEntry`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    disabled: bool | None = None
    email: str | None = None
    id: str | None = None
    invitation: bool | None = None
    lastLogin: datetime | None = None
    name: str | None = None
    twoFactorType: TwoFactorType | None = None
    username: str | None = None
