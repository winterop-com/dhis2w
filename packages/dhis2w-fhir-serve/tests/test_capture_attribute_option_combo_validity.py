"""The periods an attribute option combo may be captured for, on both halves of the rule.

DHIS2 scopes a category option by calendar window as well as by organisation unit, and refuses a
data value set whose period the window does not cover with `E8032 Untimely data entry`. The
vocabulary publishes that window on the combo concept - `dhis2-valid-from` / `dhis2-valid-to` - and
the facade reads it in both directions, exactly as it reads the organisation-unit restriction:
`$generate` draws a combo open for the period it drew, and a received response naming one that is
closed is graded on the same dial and in the same shape.

The rule the window is read under is DHIS2's own, read off 2.43 with validate-only posts: the whole
period has to sit inside the window, both ends inclusive. A category option ending `2016-10-01`
takes period `201609` and refuses `201610` although that period begins on the very day it closes.

The fixture's own combo vocabulary is the dhis2w-fhir golden, dated per test, so what is being
exercised is the published shape rather than a shape invented here.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import pytest
from dhis2w_fhir.config import FhirProject
from dhis2w_fhir_serve.app import create_app
from dhis2w_fhir_serve.capture import (
    CaptureIndexCache,
    CaptureIssue,
    CaptureNaming,
    CaptureRejection,
    ValidatedCapture,
    validate_response,
)
from dhis2w_fhir_serve.settings import ServeSettings
from dhis2w_fhir_serve.store import ResourceStore
from fixture_project import ATTRIBUTE_COMBO_CODE_SYSTEM

#: The form on the non-default category combo, and the concept its golden response is filed under.
ATTRIBUTE_COMBO_ID = "TuL8IOPzpHh"
FILED_CONCEPT = "oawMLLH7OjA"

#: The period the golden reports for: July 2026, the first to the thirty-first.
GOLDEN_PERIOD = "202607"

#: The two properties a dated concept carries, as the generator writes them.
VALID_FROM_PROPERTY = "dhis2-valid-from"
VALID_TO_PROPERTY = "dhis2-valid-to"

#: The compiled file the fixture publishes the combo vocabulary as, rewritten per test.
_CODE_SYSTEM_FILE = "CodeSystem-d2-aoc-idcDPkDtepR-cs.json"

#: Seeds a draw is asserted stable over - enough that a draw ranging wider than one answer shows it.
VARIANCE_SEEDS = (1, 2, 3, 7, 42, 9999)


def _dated_code_system(body: dict[str, Any], window: dict[str, str], *concept_codes: str) -> dict[str, Any]:
    """The combo vocabulary with a validity window on each named concept, declared as the generator does."""
    dated = copy.deepcopy(body)
    dated["property"] = [
        *(dated.get("property") or []),
        *(
            {
                "code": code,
                "uri": f"http://dhis2.org/fhir/property/{code}",
                "description": "The calendar window this combo is open for.",
                "type": "dateTime",
            }
            for code in window
        ),
    ]
    for concept in dated.get("concept") or []:
        if concept["code"] not in concept_codes:
            continue
        concept["property"] = [
            *(concept.get("property") or []),
            *({"code": code, "valueDateTime": day} for code, day in window.items()),
        ]
    return dated


def _dated_store(
    store: ResourceStore, window: dict[str, str], *, concept_codes: tuple[str, ...] = (FILED_CONCEPT,)
) -> ResourceStore:
    """The golden store with the named concepts open for `window` alone."""
    return ResourceStore(
        entries=tuple(
            entry.model_copy(update={"body": _dated_code_system(entry.body, window, *concept_codes)})
            if entry.canonical_url == ATTRIBUTE_COMBO_CODE_SYSTEM
            else entry
            for entry in store.entries
        )
    )


def _dated_project(
    project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
    window: dict[str, str],
) -> FhirProject:
    """The golden project with every combo concept open for `window` alone, where the loader reads them."""
    compiled = project.ig_directory / "fsh-generated" / "resources" / _CODE_SYSTEM_FILE
    body: dict[str, Any] = json.loads(compiled.read_text(encoding="utf-8"))
    codes = tuple(concept["code"] for concept in body.get("concept") or [])
    write_resource(compiled, _dated_code_system(body, window, *codes))
    return project


def _accept(
    body: dict[str, Any],
    indexes: CaptureIndexCache,
    naming: CaptureNaming,
    store: ResourceStore,
) -> ValidatedCapture:
    """Validate one submission, failing the test when it is refused."""
    return validate_response(json.dumps(body).encode(), indexes, naming, store, False)


def _window_issues(issues: tuple[CaptureIssue, ...]) -> tuple[CaptureIssue, ...]:
    """Only the issues the validity window raised."""
    return tuple(issue for issue in issues if issue.diagnostics is not None and "is open for" in issue.diagnostics)


async def _generate(client: httpx2.AsyncClient, resource_id: str, seed: int) -> httpx2.Response:
    """Invoke `$generate` on one served form."""
    return await client.get(f"/Questionnaire/{resource_id}/$generate", params={"seed": seed})


@asynccontextmanager
async def _serving(project: FhirProject) -> AsyncGenerator[httpx2.AsyncClient]:
    """An in-process client over one project, with the lifespan run around it."""
    app = create_app(ServeSettings(project_dir=project.project_root))
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://serve.test") as client:
            yield client


def test_a_combo_open_for_the_reported_period_is_silent(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The window covers the whole of July 2026, so the capture carries no finding."""
    store = _dated_store(capture_store, {VALID_FROM_PROPERTY: "2026-07-01", VALID_TO_PROPERTY: "2026-07-31"})

    accepted = _accept(attribute_combo_response, capture_indexes, capture_naming, store)

    assert _window_issues(accepted.warnings) == ()


def test_a_combo_closed_before_the_period_ends_is_warned_about(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """DHIS2 wants the whole period inside the window, so a combo closing mid-month refuses the month."""
    store = _dated_store(capture_store, {VALID_TO_PROPERTY: "2026-07-01"})

    accepted = _accept(attribute_combo_response, capture_indexes, capture_naming, store)

    issues = _window_issues(accepted.warnings)

    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].diagnostics is not None
    assert GOLDEN_PERIOD in issues[0].diagnostics
    assert "2026-07-01" in issues[0].diagnostics
    assert "E8032" in issues[0].diagnostics


def test_a_combo_opening_after_the_period_begins_is_warned_about(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The other end of the same rule: a window opening mid-month does not cover the month."""
    store = _dated_store(capture_store, {VALID_FROM_PROPERTY: "2026-07-02"})

    issues = _window_issues(_accept(attribute_combo_response, capture_indexes, capture_naming, store).warnings)

    assert len(issues) == 1
    assert "2026-07-02" in str(issues[0].diagnostics)


def test_strict_codes_refuses_a_combo_closed_for_the_reported_period(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The window grades on the dial the organisation-unit restriction beside it grades on."""
    store = _dated_store(capture_store, {VALID_TO_PROPERTY: "2016-10-01"})

    with pytest.raises(CaptureRejection) as raised:
        validate_response(json.dumps(attribute_combo_response).encode(), capture_indexes, capture_naming, store, True)

    assert raised.value.http_status == 422
    assert [issue.severity for issue in _window_issues(raised.value.issues)] == ["error"]


def test_a_concept_carrying_no_window_is_captured_for_any_period(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """Absence means always open, which is what DHIS2 answers for an option stating neither date."""
    store = _dated_store(capture_store, {VALID_TO_PROPERTY: "2016-10-01"}, concept_codes=("BqblOcSwGey",))

    accepted = _accept(attribute_combo_response, capture_indexes, capture_naming, store)

    assert _window_issues(accepted.warnings) == ()


async def test_generate_draws_a_combo_open_for_the_period_it_reports_for(
    capture_project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
) -> None:
    """A window running to the end of time closes nothing, so every seed still draws a combo."""
    project = _dated_project(capture_project, write_resource, {VALID_FROM_PROPERTY: "2000-01-01"})

    async with _serving(project) as client:
        drawn = [(await _generate(client, ATTRIBUTE_COMBO_ID, seed=seed)).status_code for seed in VARIANCE_SEEDS]

    assert drawn == [200] * len(VARIANCE_SEEDS)


async def test_a_form_whose_combos_all_closed_is_not_drafted(
    capture_project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
) -> None:
    """One rule, both halves: a combo closed for the period is one the facade would refuse on receipt.

    The 422 names the date axis rather than the organisation-unit one, so a reader is told which of
    the two scopes closed the form - `E8032`, not `E8025`.
    """
    project = _dated_project(capture_project, write_resource, {VALID_TO_PROPERTY: "2016-10-01"})

    async with _serving(project) as client:
        refused = await _generate(client, ATTRIBUTE_COMBO_ID, seed=3)

    outcome = refused.json()

    assert refused.status_code == 422
    assert outcome["resourceType"] == "OperationOutcome"
    assert "E8032" in outcome["issue"][0]["diagnostics"]
    assert "E8025" not in outcome["issue"][0]["diagnostics"]
