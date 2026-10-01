"""Generated OpenAPI-derived pydantic models. Do not edit by hand."""
# ruff: noqa: E501

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict
from pydantic import Field as _Field

if TYPE_CHECKING:
    from .privileged_user_stats import PrivilegedUserStats


class TwoFactorAuditSummary(_BaseModel):
    """OpenAPI schema `TwoFactorAuditSummary`."""

    model_config = _ConfigDict(extra="allow", populate_by_name=True, defer_build=True)

    byType: dict[str, int] | None = _Field(
        default=None, description="keys are class org.hisp.dhis.security.twofa.TwoFactorType"
    )
    coveragePercent: float | None = None
    disabled: int | None = None
    enabled: int | None = None
    privileged: PrivilegedUserStats | None = None
    totalUsers: int | None = None
