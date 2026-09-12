"""MCP aggregate tool tests via in-process FastMCP Client against local DHIS2."""

from __future__ import annotations

import json

import pytest
from dhis2w_mcp.server import build_server
from fastmcp import Client

pytestmark = pytest.mark.slow


def _extract_payload(result: object) -> object:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        return structured
    data = getattr(result, "data", None)
    if data is not None and hasattr(data, "model_dump"):
        return data.model_dump()
    if data is not None:
        return data
    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return json.loads(text)
    raise AssertionError(f"unexpected FastMCP result shape: {result!r}")


async def _aggregate_target(client: Client) -> tuple[str, str] | None:
    """A numeric aggregate data element of a monthly data set and one organisation unit that reports it."""
    data_sets = _extract_payload(
        await client.call_tool(
            "metadata_list",
            {
                "resource": "dataSets",
                "fields": "id,periodType,dataSetElements[dataElement[id,valueType,domainType]],organisationUnits[id]",
                "page_size": 50,
            },
        )
    )
    if not isinstance(data_sets, list):
        return None
    # Every major answers 400 to `filter=periodType:eq:Monthly` (BUGS.md #128), so the period type is matched here.
    for data_set in data_sets:
        if data_set.get("periodType") != "Monthly":
            continue
        org_units = data_set.get("organisationUnits") or []
        for entry in data_set.get("dataSetElements") or []:
            element = entry.get("dataElement") or {}
            if element.get("valueType") == "NUMBER" and element.get("domainType") == "AGGREGATE" and org_units:
                return str(element["id"]), str(org_units[0]["id"])
    return None


async def test_get_data_values_returns_envelope(
    local_url: str, local_pat: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Get data values returns envelope."""
    if not local_pat:
        pytest.skip("DHIS2_PAT not set — run `make dhis2-run` to populate")
    monkeypatch.setenv("DHIS2_URL", local_url)
    monkeypatch.setenv("DHIS2_PAT", local_pat)

    server = build_server()
    async with Client(server) as client:
        datasets = _extract_payload(
            await client.call_tool(
                "metadata_list",
                {"resource": "dataSets", "fields": "id,name", "page_size": 1},
            )
        )
        org_units = _extract_payload(
            await client.call_tool(
                "metadata_list",
                {"resource": "organisationUnits", "fields": "id,name", "page_size": 1},
            )
        )
        if not (isinstance(datasets, list) and datasets and isinstance(org_units, list) and org_units):
            pytest.skip("instance missing dataSets or organisationUnits")

        result = await client.call_tool(
            "data_aggregate_get",
            {
                "data_set": datasets[0]["id"],
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "org_unit": org_units[0]["id"],
                "children": True,
                "limit": 5,
            },
        )

    envelope = _extract_payload(result)
    assert isinstance(envelope, dict)
    assert "dataValues" in envelope
    assert isinstance(envelope["dataValues"], list)


async def test_push_data_values_dry_run(local_url: str, local_pat: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Push data values dry run."""
    if not local_pat:
        pytest.skip("DHIS2_PAT not set — run `make dhis2-run` to populate")
    monkeypatch.setenv("DHIS2_URL", local_url)
    monkeypatch.setenv("DHIS2_PAT", local_pat)

    server = build_server()
    async with Client(server) as client:
        target = await _aggregate_target(client)
        if target is None:
            pytest.skip("instance missing an aggregate data element in a monthly data set")
        data_element_id, org_unit_id = target
        result = await client.call_tool(
            "data_aggregate_push",
            {
                "data_values": [
                    {
                        "dataElement": data_element_id,
                        "orgUnit": org_unit_id,
                        "period": "202401",
                        "value": "7",
                    }
                ],
                "dry_run": True,
            },
        )

    response = _extract_payload(result)
    assert isinstance(response, dict)
    assert any(key in response for key in ("status", "httpStatus", "importCount", "response"))
