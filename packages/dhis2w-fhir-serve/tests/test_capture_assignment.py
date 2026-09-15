"""Capture against what a form admits as a place to report from, on both positions of the dial.

The assignment artifact is optional by design, so the cases that matter are the ones the design
turns on: an in-assignment unit is silent, and an out-of-assignment unit warns by default and
refuses under `--strict-codes` - the same grading a coded answer takes, because both describe drift
between a client and the instance rather than a malformed submission.

A form publishing no assignment is assigned everywhere, and everywhere is the registry this server
publishes. So the same unit is graded against that instead: a unit the registry does not hold takes
the same dial, and the guide's own worked example - which stands for no place on any instance - is
refused whatever the dial says.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from dhis2w_fhir_serve.capture import (
    CaptureIndexCache,
    CaptureIssue,
    CaptureNaming,
    CaptureRejection,
    ValidatedCapture,
    validate_response,
)
from dhis2w_fhir_serve.store import ResourceStore, StoreEntry

#: The canonical the dhis2w-fhir goldens were compiled under, as `capture_project` serves them.
CANONICAL = "http://localhost:8080/fhir"
AGGREGATE_QUESTIONNAIRE = f"{CANONICAL}/Questionnaire/BfMAe6Itzgt"


def _accept(
    body: dict[str, Any],
    indexes: CaptureIndexCache,
    naming: CaptureNaming,
    store: ResourceStore,
    strict_codes: bool = False,
) -> ValidatedCapture:
    """Validate one submission, failing the test when it is refused."""
    return validate_response(json.dumps(body).encode(), indexes, naming, store, strict_codes)


def _refuse(
    body: dict[str, Any],
    indexes: CaptureIndexCache,
    naming: CaptureNaming,
    store: ResourceStore,
    strict_codes: bool = False,
) -> CaptureRejection:
    """Validate one submission, failing the test when it is accepted."""
    with pytest.raises(CaptureRejection) as raised:
        validate_response(json.dumps(body).encode(), indexes, naming, store, strict_codes)
    return raised.value


def _errors(rejection: CaptureRejection) -> tuple[CaptureIssue, ...]:
    """Only the issues that refused the submission."""
    return tuple(issue for issue in rejection.issues if issue.is_error())


_ASSIGNMENT_EXTENSION_URL = f"{CANONICAL}/StructureDefinition/d2-organisation-unit-assignment"
_ASSIGNMENT_LIST_ID = "d2-ds-BfMAe6Itzgt-org-units"

#: The one unit the fixture's assignment admits - the golden aggregate response reports for it.
_ADMITTED_LOCATION = "Location/ImspTQPwCqd"


def _assignment_list(*references: str) -> dict[str, Any]:
    """The published assignment artifact, in the shape the generate target writes it."""
    return {
        "resourceType": "List",
        "id": _ASSIGNMENT_LIST_ID,
        "status": "current",
        "mode": "snapshot",
        "title": "Child Health - assigned organisation units",
        "entry": [{"item": {"reference": reference}} for reference in references],
    }


def _scoped_store(store: ResourceStore, *references: str) -> ResourceStore:
    """The golden store with the aggregate form scoped by an assignment List naming `references`."""
    entries: list[StoreEntry] = []
    for entry in store.entries:
        if entry.canonical_url != AGGREGATE_QUESTIONNAIRE:
            entries.append(entry)
            continue
        body = copy.deepcopy(entry.body)
        extensions = list(body.get("extension") or [])
        extensions.append(
            {
                "url": _ASSIGNMENT_EXTENSION_URL,
                "valueReference": {"reference": f"List/{_ASSIGNMENT_LIST_ID}"},
            }
        )
        body["extension"] = extensions
        entries.append(entry.model_copy(update={"body": body}))
    entries.append(
        StoreEntry(
            resource_type="List",
            resource_id=_ASSIGNMENT_LIST_ID,
            source="test",
            body=_assignment_list(*references),
        )
    )
    return ResourceStore(entries=tuple(entries))


def _assignment_issues(issues: tuple[CaptureIssue, ...]) -> tuple[CaptureIssue, ...]:
    """Only the issues the assignment phase raised."""
    return tuple(issue for issue in issues if issue.code == "business-rule")


#: The guide's own worked example of the organisation-unit profile, which publishes no unit.
_EXEMPLAR_LOCATION = "Location/d2-location-example"

#: A shaped reference to no unit of this registry at all.
_UNPUBLISHED_LOCATION = "Location/NowhereNear"


def test_a_form_publishing_no_assignment_is_scoped_to_the_whole_registry(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """Absence means every published unit may report the form, and every published unit is silent."""
    aggregate_response["subject"] = {"reference": "Location/O6uvpzGd5pu"}

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, capture_store)

    assert _assignment_issues(accepted.warnings) == ()


@pytest.mark.parametrize("strict_codes", [False, True])
def test_a_form_publishing_no_assignment_still_grades_a_unit_the_registry_does_not_hold(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
    strict_codes: bool,
) -> None:
    """ "Assigned everywhere" is every unit this server publishes, not every string shaped like one."""
    aggregate_response["subject"] = {"reference": _UNPUBLISHED_LOCATION}

    if strict_codes:
        issues = _assignment_issues(
            _errors(_refuse(aggregate_response, capture_indexes, capture_naming, capture_store, strict_codes=True))
        )
    else:
        issues = _assignment_issues(
            _accept(aggregate_response, capture_indexes, capture_naming, capture_store).warnings
        )

    assert len(issues) == 1
    assert issues[0].expression == "QuestionnaireResponse.subject.reference"
    assert issues[0].diagnostics is not None
    assert f"`{_UNPUBLISHED_LOCATION}` is not among the organisation units this server publishes" in (
        issues[0].diagnostics
    )


@pytest.mark.parametrize("strict_codes", [False, True])
def test_a_form_publishing_no_assignment_refuses_the_guides_own_worked_example(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
    strict_codes: bool,
) -> None:
    """The exemplar illustrates the profile and stands for no place, so no dial position stores a capture at it."""
    aggregate_response["subject"] = {"reference": _EXEMPLAR_LOCATION}

    rejection = _refuse(aggregate_response, capture_indexes, capture_naming, capture_store, strict_codes=strict_codes)

    assert rejection.http_status == 422
    refused = _assignment_issues(_errors(rejection))
    assert len(refused) == 1
    assert refused[0].expression == "QuestionnaireResponse.subject.reference"
    assert refused[0].diagnostics is not None
    assert f"`{_EXEMPLAR_LOCATION}` is a worked example of this guide, not a published organisation unit" in (
        refused[0].diagnostics
    )


def test_a_project_publishing_no_registry_grades_the_reference_shape_alone(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """With no organisation unit published there is no set to check against, and none is invented."""
    without_registry = ResourceStore(
        entries=tuple(entry for entry in capture_store.entries if entry.resource_type != "Location")
    )
    aggregate_response["subject"] = {"reference": _UNPUBLISHED_LOCATION}

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, without_registry)

    assert _assignment_issues(accepted.warnings) == ()


def test_a_subject_inside_the_assignment_is_silent(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The form's own assignment admits the unit the golden reports for, so nothing is noted."""
    store = _scoped_store(capture_store, _ADMITTED_LOCATION, "Location/O6uvpzGd5pu")

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, store)

    assert accepted.warnings == ()


def test_a_subject_outside_the_assignment_is_a_warning_by_default(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The submission is stored and the receipt says DHIS2 will refuse the write."""
    store = _scoped_store(capture_store, "Location/O6uvpzGd5pu")

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, store)

    noted = _assignment_issues(accepted.warnings)
    assert len(noted) == 1
    assert noted[0].severity == "warning"
    assert noted[0].expression == "QuestionnaireResponse.subject.reference"
    assert noted[0].diagnostics is not None
    assert f"`{_ADMITTED_LOCATION}` is not in the form's organisation-unit assignment" in noted[0].diagnostics
    assert "E1029" in noted[0].diagnostics


def test_a_form_with_an_assignment_also_grades_whether_the_guide_publishes_the_unit(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """Two facts, two findings: the guide publishes no such Location, and the List does not name it.

    A List saying nothing about a reference is not the List answering whether the reference names a
    published organisation unit at all, so the existence question is asked of an assigned form
    exactly as it is asked of an unassigned one.
    """
    aggregate_response["subject"] = {"reference": _UNPUBLISHED_LOCATION}
    store = _scoped_store(capture_store, _ADMITTED_LOCATION)

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, store)

    noted = [issue.diagnostics or "" for issue in _assignment_issues(accepted.warnings)]
    assert any("is not among the organisation units this server publishes" in text for text in noted)
    assert any("is not in the form's organisation-unit assignment" in text for text in noted)


def test_a_strict_facade_refuses_an_unpublished_subject_of_an_assigned_form(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The existence finding grades on the dial the assignment finding grades on, on a form with a List."""
    aggregate_response["subject"] = {"reference": _UNPUBLISHED_LOCATION}
    store = _scoped_store(capture_store, _ADMITTED_LOCATION)

    rejection = _refuse(aggregate_response, capture_indexes, capture_naming, store, strict_codes=True)

    assert rejection.http_status == 422
    refused = [issue.diagnostics or "" for issue in _errors(rejection)]
    assert any("is not among the organisation units this server publishes" in text for text in refused)


def test_a_subject_the_assignment_admits_and_the_guide_publishes_is_silent_on_both(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """Asking the existence question of every form adds no finding to a capture that is simply right."""
    store = _scoped_store(capture_store, _ADMITTED_LOCATION)

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, store)

    assert accepted.warnings == ()


def test_a_strict_facade_refuses_the_subject_a_lenient_one_warns_about(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The dial that grades a coded answer grades the organisation unit the same way."""
    store = _scoped_store(capture_store, "Location/O6uvpzGd5pu")

    rejection = _refuse(aggregate_response, capture_indexes, capture_naming, store, strict_codes=True)

    assert rejection.http_status == 422
    refused = _assignment_issues(_errors(rejection))
    assert len(refused) == 1
    assert refused[0].expression == "QuestionnaireResponse.subject.reference"


#: The unit the golden aggregate response reports for, named absolutely under the authority this
#: project publishes its organisation units at - the spelling a guide whose registry a package
#: publishes uses, and the only one that resolves across an implementation-guide package dependency.
_ADMITTED_LOCATION_ABSOLUTE = f"{CANONICAL}/{_ADMITTED_LOCATION}"

#: A Location under somebody else's authority. The id is this project's, the registry is not.
_FOREIGN_LOCATION = f"https://hapi.fhir.org/baseR4/{_ADMITTED_LOCATION}"


def test_an_absolute_assignment_entry_admits_the_unit_it_names(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """One unit, two spellings: an assignment written against a registry package admits a relative subject."""
    store = _scoped_store(capture_store, _ADMITTED_LOCATION_ABSOLUTE)

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, store)

    assert _assignment_issues(accepted.warnings) == ()


def test_an_absolute_assignment_entry_still_refuses_a_unit_it_does_not_name(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """Reading the id off an absolute entry narrows the assignment to that unit, not to the registry."""
    store = _scoped_store(capture_store, f"{CANONICAL}/Location/O6uvpzGd5pu")

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, store)

    assert len(_assignment_issues(accepted.warnings)) == 1


def test_an_assignment_entry_naming_something_other_than_a_location_admits_nothing(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """An `Organization` entry names the same DHIS2 unit and is still not a Location the form is captured at."""
    store = _scoped_store(capture_store, "Organization/ImspTQPwCqd", f"{CANONICAL}/Organization/x")

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, store)

    assert len(_assignment_issues(accepted.warnings)) == 1


def test_an_empty_assignment_admits_nothing(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """A form assigned to no published unit is a form no published unit may report for."""
    store = _scoped_store(capture_store)

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, store)

    assert len(_assignment_issues(accepted.warnings)) == 1


def test_an_assignment_the_facade_does_not_serve_checks_nothing(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """A named List the store does not hold is the project's incomplete build, not the client's mistake."""
    store = _scoped_store(capture_store, "Location/O6uvpzGd5pu")
    without_list = ResourceStore(entries=tuple(entry for entry in store.entries if entry.resource_type != "List"))

    accepted = _accept(aggregate_response, capture_indexes, capture_naming, without_list)

    assert _assignment_issues(accepted.warnings) == ()


@pytest.mark.parametrize("strict_codes", [False, True])
def test_a_tracker_events_organisation_unit_extension_is_graded_the_same_way(
    tracker_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
    strict_codes: bool,
) -> None:
    """A tracker event carries its unit on an extension, and the assignment reads it from there."""
    canonical = tracker_response["questionnaire"]
    entries: list[StoreEntry] = []
    for entry in capture_store.entries:
        if entry.canonical_url != canonical:
            entries.append(entry)
            continue
        body = copy.deepcopy(entry.body)
        body["extension"] = [
            *(body.get("extension") or []),
            {"url": _ASSIGNMENT_EXTENSION_URL, "valueReference": {"reference": f"List/{_ASSIGNMENT_LIST_ID}"}},
        ]
        entries.append(entry.model_copy(update={"body": body}))
    entries.append(
        StoreEntry(
            resource_type="List",
            resource_id=_ASSIGNMENT_LIST_ID,
            source="test",
            body=_assignment_list("Location/SomewhereElse"),
        )
    )
    store = ResourceStore(entries=tuple(entries))

    if strict_codes:
        rejection = _refuse(tracker_response, capture_indexes, capture_naming, store, strict_codes=True)
        issues = _assignment_issues(_errors(rejection))
    else:
        issues = _assignment_issues(_accept(tracker_response, capture_indexes, capture_naming, store).warnings)

    assert len(issues) == 1
    assert issues[0].expression == "QuestionnaireResponse.extension"


def test_the_rejection_is_raised_with_every_other_phase_already_cleared(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The assignment phase runs after the form resolves, so it never masks an unreadable submission."""
    store = _scoped_store(capture_store, "Location/O6uvpzGd5pu")
    aggregate_response["questionnaire"] = f"{CANONICAL}/Questionnaire/NotServed01"

    with pytest.raises(CaptureRejection) as raised:
        validate_response(json.dumps(aggregate_response).encode(), capture_indexes, capture_naming, store, False)

    assert _assignment_issues(raised.value.issues) == ()


def _temporal_response(unit_reference: str) -> dict[str, Any]:
    """One submission against the temporal event form, answering its ORGANISATION_UNIT question."""
    return {
        "resourceType": "QuestionnaireResponse",
        "extension": [{"url": f"{CANONICAL}/StructureDefinition/d2-form-type", "valueCode": "event"}],
        "questionnaire": f"{CANONICAL}/Questionnaire/PrTemporal1",
        "status": "completed",
        "subject": {"reference": _ADMITTED_LOCATION},
        "authored": "2026-07-25T16:00:00Z",
        "item": [{"linkId": "DeVisitUnit1", "answer": [{"valueReference": {"reference": unit_reference}}]}],
    }


def _temporal_store(store: ResourceStore, *references: str) -> ResourceStore:
    """The golden store with the temporal event form scoped by an assignment List naming `references`."""
    canonical = f"{CANONICAL}/Questionnaire/PrTemporal1"
    entries: list[StoreEntry] = []
    for entry in store.entries:
        if entry.canonical_url != canonical:
            entries.append(entry)
            continue
        body = copy.deepcopy(entry.body)
        body["extension"] = [
            *(body.get("extension") or []),
            {"url": _ASSIGNMENT_EXTENSION_URL, "valueReference": {"reference": f"List/{_ASSIGNMENT_LIST_ID}"}},
        ]
        entries.append(entry.model_copy(update={"body": body}))
    entries.append(
        StoreEntry(
            resource_type="List",
            resource_id=_ASSIGNMENT_LIST_ID,
            source="test",
            body=_assignment_list(*references),
        )
    )
    return ResourceStore(entries=tuple(entries))


def test_an_organisation_unit_answer_inside_the_assignment_is_silent(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """An ORGANISATION_UNIT answer is checked against the same List the subject is."""
    store = _temporal_store(capture_store, _ADMITTED_LOCATION)

    accepted = _accept(_temporal_response(_ADMITTED_LOCATION), capture_indexes, capture_naming, store)

    assert _assignment_issues(accepted.warnings) == ()


@pytest.mark.parametrize("strict_codes", [False, True])
def test_an_organisation_unit_answer_outside_the_assignment_grades_on_the_dial(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
    strict_codes: bool,
) -> None:
    """The answer takes the same warning-or-refusal grading the subject takes."""
    store = _temporal_store(capture_store, _ADMITTED_LOCATION)
    body = _temporal_response("Location/O6uvpzGd5pu")

    if strict_codes:
        issues = _assignment_issues(_errors(_refuse(body, capture_indexes, capture_naming, store, strict_codes=True)))
    else:
        issues = _assignment_issues(_accept(body, capture_indexes, capture_naming, store).warnings)

    assert len(issues) == 1
    assert issues[0].expression == "QuestionnaireResponse.item.where(linkId='DeVisitUnit1')"


def test_an_organisation_unit_answer_written_absolutely_is_read_as_the_unit_it_names(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """A response naming its unit under the registry package's canonical is graded against the same unit."""
    store = _temporal_store(capture_store, _ADMITTED_LOCATION_ABSOLUTE)

    accepted = _accept(_temporal_response(_ADMITTED_LOCATION_ABSOLUTE), capture_indexes, capture_naming, store)

    assert _assignment_issues(accepted.warnings) == ()


def test_an_organisation_unit_answer_on_an_unassigned_form_is_graded_against_the_registry(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The form publishes no assignment, so the answer is graded against what the server publishes."""
    accepted = _accept(_temporal_response(_UNPUBLISHED_LOCATION), capture_indexes, capture_naming, capture_store)

    noted = _assignment_issues(accepted.warnings)
    assert len(noted) == 1
    assert noted[0].severity == "warning"
    assert noted[0].expression == "QuestionnaireResponse.item.where(linkId='DeVisitUnit1')"


def test_an_organisation_unit_answer_naming_the_worked_example_is_refused(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The exemplar is no more reportable as an answer than it is as the subject of the submission."""
    rejection = _refuse(_temporal_response(_EXEMPLAR_LOCATION), capture_indexes, capture_naming, capture_store)

    refused = _assignment_issues(_errors(rejection))
    assert len(refused) == 1
    assert refused[0].expression == "QuestionnaireResponse.item.where(linkId='DeVisitUnit1')"
    assert refused[0].diagnostics is not None
    assert "E1011" in refused[0].diagnostics


def test_a_subject_naming_a_location_under_another_authority_is_refused(
    aggregate_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The id is this project's and the registry is not, so the reference names a different place."""
    store = _scoped_store(capture_store, _ADMITTED_LOCATION)
    aggregate_response["subject"] = {"reference": _FOREIGN_LOCATION}

    rejection = _refuse(aggregate_response, capture_indexes, capture_naming, store)

    refused = _errors(rejection)
    assert len(refused) == 1
    assert refused[0].expression == "QuestionnaireResponse.subject.reference"
    assert refused[0].diagnostics is not None
    assert "names an organisation unit under `https://hapi.fhir.org/baseR4`" in refused[0].diagnostics
    assert f"published under `{CANONICAL}`" in refused[0].diagnostics


def test_an_organisation_unit_answer_under_another_authority_is_refused(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """An answer naming somebody else's registry is refused rather than read as a unit of this one."""
    store = _temporal_store(capture_store, _ADMITTED_LOCATION)

    rejection = _refuse(_temporal_response(_FOREIGN_LOCATION), capture_indexes, capture_naming, store)

    refused = _errors(rejection)
    assert len(refused) == 1
    assert refused[0].expression == "QuestionnaireResponse.item.where(linkId='DeVisitUnit1')"
    assert refused[0].diagnostics is not None
    assert "names an organisation unit under `https://hapi.fhir.org/baseR4`" in refused[0].diagnostics
