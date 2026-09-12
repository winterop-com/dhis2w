"""End-to-end aggregate CLI tests against local DHIS2."""

from __future__ import annotations

import json
import secrets

import pytest
from dhis2w_cli.main import build_app
from typer.testing import CliRunner

pytestmark = pytest.mark.slow


def _setup_env(monkeypatch: pytest.MonkeyPatch, local_url: str, local_pat: str | None) -> None:
    if not local_pat:
        pytest.skip("DHIS2_PAT not set — run `make dhis2-run` to populate")
    monkeypatch.setenv("DHIS2_URL", local_url)
    monkeypatch.setenv("DHIS2_PAT", local_pat)


def _first_uid(runner: CliRunner, resource: str) -> str | None:
    result = runner.invoke(
        build_app(),
        ["--json", "metadata", "list", resource, "--fields", "id,name", "--page-size", "1"],
    )
    assert result.exit_code == 0, result.output
    items = json.loads(result.output)
    if not items:
        return None
    uid = items[0].get("id")
    return str(uid) if uid else None


def test_aggregate_get_returns_envelope(local_url: str, local_pat: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aggregate get returns envelope."""
    _setup_env(monkeypatch, local_url, local_pat)
    runner = CliRunner()
    data_set = _first_uid(runner, "dataSets")
    org_unit = _first_uid(runner, "organisationUnits")
    if not (data_set and org_unit):
        pytest.skip("instance missing dataSets or organisationUnits")

    result = runner.invoke(
        build_app(),
        [
            "--json",
            "data",
            "aggregate",
            "get",
            "--data-set",
            data_set,
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-31",
            "--org-unit",
            org_unit,
            "--children",
            "--limit",
            "5",
        ],
    )
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert "dataValues" in envelope
    assert isinstance(envelope["dataValues"], list)


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


def test_aggregate_push_dry_run(
    local_url: str, local_pat: str | None, monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Aggregate push dry run."""
    _setup_env(monkeypatch, local_url, local_pat)
    runner = CliRunner()

    # A numeric aggregate data element of a monthly data set, posted for an organisation unit that reports it.
    target = _aggregate_target(runner)
    if target is None:
        pytest.skip("instance missing an aggregate data element in a monthly data set")
    data_element_id, org_unit_id = target

    import_payload = {
        "dataValues": [
            {
                "dataElement": data_element_id,
                "orgUnit": org_unit_id,
                "period": "202401",
                "value": str(secrets.randbelow(10) + 1),
            }
        ]
    }
    import_file = tmp_path / "values.json"  # type: ignore[operator]
    import_file.write_text(json.dumps(import_payload))

    result = runner.invoke(
        build_app(),
        ["--json", "data", "aggregate", "push", str(import_file), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    response = json.loads(result.output)
    # DHIS2 dry-run response always includes a status/httpStatus or importCount summary
    assert any(key in response for key in ("status", "httpStatus", "importCount", "response"))
