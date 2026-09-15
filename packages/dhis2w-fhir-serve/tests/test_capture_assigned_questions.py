"""A question an `ASSIGN` program rule computes, on both halves of the one rule.

DHIS2 works such a value out itself on import and takes what a client sent for it only when it is
empty or already equal to the calculated one, refusing the whole document with `E1307` otherwise. So
`$generate` answers the question with nothing at all - the one value that is accepted whatever the
rule computes - and a submission that does answer it is told which rule is waiting and what the
instance does with a value that disagrees.

It is a warning and never a refusal: a client that ran the same arithmetic and sent the result is
sending something DHIS2 accepts, and this server evaluates no rule and so cannot tell the two apart.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2
from dhis2w_fhir_serve.capture import (
    CaptureIndexCache,
    CaptureIssue,
    CaptureNaming,
    ValidatedCapture,
    validate_response,
)
from dhis2w_fhir_serve.store import ResourceStore
from fixture_project import (
    ASSIGNED_PRESSURE_LINK_ID,
    ASSIGNED_PRESSURE_RULE_NAME,
    ASSIGNED_PRESSURE_RULE_UID,
)

#: The canonical the dhis2w-fhir goldens were compiled under, as `capture_project` serves them.
CANONICAL = "http://localhost:8080/fhir"
TRACKED_ENTITY_SYSTEM = "http://dhis2.org/fhir/id/tracked-entity"
TRACKER_ENROLLMENT_SYSTEM = "http://dhis2.org/fhir/id/tracker-enrollment"

#: The stage form whose instance holds the ASSIGN rule, and a question no rule of it computes.
ANC_STAGE_ID = "PsAncVisit1"
ANC_QUESTIONNAIRE = f"{CANONICAL}/Questionnaire/{ANC_STAGE_ID}"
UNASSIGNED_LINK_ID = "DeAncVisNo1"

#: Seeds the draw is asserted stable over - one that sometimes answered it would be luck, not a rule.
VARIANCE_SEEDS = (1, 2, 3, 7, 42, 9999)


def _anc_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    """One submission against the ANC tracker stage, which is the form the ASSIGN rule is declared on."""
    return {
        "resourceType": "QuestionnaireResponse",
        "extension": [
            {
                "url": f"{CANONICAL}/StructureDefinition/d2-organisation-unit",
                "valueReference": {"reference": "Location/ImspTQPwCqd"},
            },
            {
                "url": f"{CANONICAL}/StructureDefinition/d2-tracker-enrollment",
                "valueIdentifier": {"system": TRACKER_ENROLLMENT_SYSTEM, "value": "gxMz7Qje7pk"},
            },
            {"url": f"{CANONICAL}/StructureDefinition/d2-form-type", "valueCode": "tracker-event"},
        ],
        "questionnaire": ANC_QUESTIONNAIRE,
        "status": "completed",
        "subject": {"identifier": {"system": TRACKED_ENTITY_SYSTEM, "value": "tPpcmcRWO0g"}, "type": "Patient"},
        "authored": "2026-07-13T15:00:00Z",
        "item": items,
    }


def _accept(
    body: dict[str, Any],
    indexes: CaptureIndexCache,
    naming: CaptureNaming,
    store: ResourceStore,
    strict_codes: bool = False,
) -> ValidatedCapture:
    """Validate one submission, failing the test when it is refused."""
    return validate_response(json.dumps(body).encode(), indexes, naming, store, strict_codes)


def _assign_issues(issues: tuple[CaptureIssue, ...]) -> tuple[CaptureIssue, ...]:
    """Only the issues raised about a question DHIS2 computes itself."""
    return tuple(issue for issue in issues if issue.diagnostics is not None and "E1307" in issue.diagnostics)


def _answered(response: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Every answered link id of a generated response, flattened out of its item tree."""
    answers: dict[str, list[dict[str, Any]]] = {}

    def walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            if item.get("answer"):
                answers[item["linkId"]] = item["answer"]
            walk(item.get("item") or [])

    walk(response.get("item") or [])
    return answers


async def _generated(client: httpx2.AsyncClient, seed: int) -> dict[str, Any]:
    """One draft of the ANC stage form, drawn from the named seed."""
    body: dict[str, Any] = (await client.get(f"/Questionnaire/{ANC_STAGE_ID}/$generate?seed={seed}")).json()
    return body


async def test_generate_leaves_a_question_dhis2_computes_unanswered(
    capture_client: httpx2.AsyncClient,
) -> None:
    """The one answer E1307 always accepts is no answer, and no rule is evaluated to find another."""
    answered = _answered(await _generated(capture_client, seed=5))

    assert ASSIGNED_PRESSURE_LINK_ID not in answered
    assert UNASSIGNED_LINK_ID in answered


async def test_generate_leaves_it_unanswered_whatever_the_seed(capture_client: httpx2.AsyncClient) -> None:
    """A draw that sometimes answered it would make the round trip a matter of luck."""
    drawn = [
        ASSIGNED_PRESSURE_LINK_ID in _answered(await _generated(capture_client, seed=seed)) for seed in VARIANCE_SEEDS
    ]

    assert drawn == [False] * len(VARIANCE_SEEDS)


async def test_a_generated_draft_of_such_a_form_still_posts_back(capture_client: httpx2.AsyncClient) -> None:
    """Leaving the question out is not leaving the form incomplete - the rule's value is not ours to send."""
    generated = await _generated(capture_client, seed=5)

    posted = await capture_client.post(
        "/QuestionnaireResponse",
        content=json.dumps(generated).encode(),
        headers={"Content-Type": "application/fhir+json"},
    )

    assert posted.status_code == 201
    assert not [issue for issue in posted.json()["issue"] if "E1307" in (issue.get("diagnostics") or "")]


def test_an_answer_to_a_computed_question_is_a_warning_naming_the_rule(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The receipt says which rule computes it and what DHIS2 does with a value that disagrees."""
    body = _anc_response([{"linkId": ASSIGNED_PRESSURE_LINK_ID, "answer": [{"valueInteger": 120}]}])

    accepted = _accept(body, capture_indexes, capture_naming, capture_store)

    noted = _assign_issues(accepted.warnings)
    assert len(noted) == 1
    assert noted[0].severity == "warning"
    assert noted[0].diagnostics is not None
    assert ASSIGNED_PRESSURE_LINK_ID in noted[0].diagnostics
    assert ASSIGNED_PRESSURE_RULE_NAME in noted[0].diagnostics
    assert ASSIGNED_PRESSURE_RULE_UID in noted[0].diagnostics


def test_an_answer_to_a_computed_question_is_never_a_refusal(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """A client that ran the rule's own arithmetic sends what DHIS2 accepts, so a strict server takes it too."""
    body = _anc_response([{"linkId": ASSIGNED_PRESSURE_LINK_ID, "answer": [{"valueInteger": 120}]}])

    accepted = _accept(body, capture_indexes, capture_naming, capture_store, strict_codes=True)

    assert [issue.severity for issue in _assign_issues(accepted.warnings)] == ["warning"]


def test_a_question_no_rule_computes_carries_no_such_note(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The note is about the rule, so a question no rule names is answered without one."""
    body = _anc_response([{"linkId": UNASSIGNED_LINK_ID, "answer": [{"valueInteger": 2}]}])

    accepted = _accept(body, capture_indexes, capture_naming, capture_store)

    assert _assign_issues(accepted.warnings) == ()


def test_leaving_a_computed_question_unanswered_carries_no_note(
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """An empty answer is what the rule asks for, so there is nothing to say about it."""
    body = _anc_response(
        [
            {"linkId": UNASSIGNED_LINK_ID, "answer": [{"valueInteger": 2}]},
            {"linkId": "DeAncDanger", "answer": [{"valueBoolean": False}]},
        ]
    )

    accepted = _accept(body, capture_indexes, capture_naming, capture_store)

    assert _assign_issues(accepted.warnings) == ()
