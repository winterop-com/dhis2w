"""End-to-end analytics CLI tests against local DHIS2."""

from __future__ import annotations

import json

import pytest
from dhis2w_cli.main import build_app
from typer.testing import CliRunner

pytestmark = pytest.mark.slow


def _setup_env(monkeypatch: pytest.MonkeyPatch, local_url: str, local_pat: str | None) -> None:
    if not local_pat:
        pytest.skip("DHIS2_PAT not set — run `make dhis2-run` to populate")
    monkeypatch.setenv("DHIS2_URL", local_url)
    monkeypatch.setenv("DHIS2_PAT", local_pat)


def _first_uid(runner: CliRunner, resource: str, extra_args: list[str] | None = None) -> str | None:
    args = ["--json", "metadata", "list", resource, "--fields", "id,name", "--page-size", "1"]
    if extra_args:
        args = args + extra_args
    result = runner.invoke(build_app(), args)
    assert result.exit_code == 0, result.output
    items = json.loads(result.output)
    return str(items[0]["id"]) if items else None


def _aggregate_target(runner: CliRunner) -> tuple[str, str] | None:
    """A numeric aggregate data element of a monthly data set and one organisation unit that reports it."""
    result = runner.invoke(
        build_app(),
        [
            "--json",
            "metadata",
            "list",
            "dataSets",
            "--fields",
            "id,periodType,dataSetElements[dataElement[id,valueType,domainType]],organisationUnits[id]",
            "--page-size",
            "50",
        ],
    )
    assert result.exit_code == 0, result.output
    # Every major answers 400 to `filter=periodType:eq:Monthly` (BUGS.md #128), so the period type is matched here.
    for data_set in json.loads(result.output):
        if data_set.get("periodType") != "Monthly":
            continue
        org_units = data_set.get("organisationUnits") or []
        for entry in data_set.get("dataSetElements") or []:
            element = entry.get("dataElement") or {}
            if element.get("valueType") == "NUMBER" and element.get("domainType") == "AGGREGATE" and org_units:
                return str(element["id"]), str(org_units[0]["id"])
    return None


def test_analytics_query_returns_response(
    local_url: str, local_pat: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Analytics query returns response."""
    _setup_env(monkeypatch, local_url, local_pat)
    runner = CliRunner()
    target = _aggregate_target(runner)
    org_unit = _first_uid(runner, "organisationUnits", ["--filter", "level:eq:1"])
    if target is None or not org_unit:
        pytest.skip("instance missing an aggregate data element in a monthly data set")
    data_element, _ = target

    result = runner.invoke(
        build_app(),
        [
            "--json",
            "analytics",
            "query",
            "--dimension",
            f"dx:{data_element}",
            "--dimension",
            "pe:LAST_12_MONTHS",
            "--dimension",
            f"ou:{org_unit}",
            "--skip-meta",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any(key in payload for key in ("headers", "rows", "metaData"))
