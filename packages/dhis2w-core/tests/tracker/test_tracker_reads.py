"""Query-key coverage for the tracker read services on every version tree.

DHIS2 2.42.6 and 2.43.1 read the organisation unit mode from `orgUnitMode` on
every tracker read, take the units as `orgUnit` on `/api/tracker/events` and
as `orgUnits` on the tracked entity and enrollment reads, and drop or refuse
the other spellings (BUGS.md #113). These assert each read
service sends the key its endpoint honours, on v41 / v42 / v43 alike.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import httpx
import respx
from dhis2w_core.profile import profile_from_env

_HOST = "https://dhis2.example"


@respx.mock
async def test_list_events_sends_org_unit_mode(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """`list_events` rides the mode on `orgUnitMode`, never on `ouMode`."""
    mock_system_info(core_version)
    route = respx.get(f"{_HOST}/api/tracker/events").mock(
        return_value=httpx.Response(200, json={"events": [], "pager": {"page": 1, "pageSize": 50}}),
    )
    service = plugin_service("tracker")
    events = await service.list_events(profile_from_env(), program="progUid0001", org_unit="ouUidAAA001")
    assert events == []
    params = route.calls.last.request.url.params
    assert params["orgUnitMode"] == "DESCENDANTS"
    assert "ouMode" not in params


@respx.mock
async def test_list_enrollments_sends_ou_mode(
    core_version: str,
    core_profile: None,
    mock_system_info: Callable[..., None],
    plugin_service: Callable[[str], ModuleType],
) -> None:
    """`list_enrollments` rides the mode on `orgUnitMode` and the units on `orgUnits`."""
    mock_system_info(core_version)
    route = respx.get(f"{_HOST}/api/tracker/enrollments").mock(
        return_value=httpx.Response(200, json={"enrollments": [], "pager": {"page": 1, "pageSize": 50}}),
    )
    service = plugin_service("tracker")
    enrollments = await service.list_enrollments(profile_from_env(), program="progUid0001", org_unit="ouUidAAA001")
    assert enrollments == []
    params = route.calls.last.request.url.params
    assert params["orgUnitMode"] == "DESCENDANTS"
    assert "ouMode" not in params
