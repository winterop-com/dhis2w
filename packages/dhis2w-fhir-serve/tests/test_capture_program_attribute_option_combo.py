"""Capture against the attribute option combo an event program's form declares.

A DHIS2 program whose category combo is not the default one keys every event it files by an
attribute option combo of that combo, and refuses one filed under the default with `E1055`. So a
program form declares its vocabulary exactly as a data set's does, its draft draws one concept out
of it, and the same three gradings the data-set path applies apply here - a declared vocabulary left
unnamed, a concept the published CodeSystem does not hold, and a coding the store really holds.

The form is the golden event Questionnaire with that declaration written onto it, because the
declaration is the only thing about a program form that this path reads.
"""

from __future__ import annotations

import copy
import datetime
import json
from typing import Any

import pytest
from dhis2w_fhir.r4 import Questionnaire
from dhis2w_fhir_serve.capture import (
    CaptureIndexCache,
    CaptureIssue,
    CaptureNaming,
    CaptureRejection,
    ValidatedCapture,
    build_capture_index,
    validate_response,
)
from dhis2w_fhir_serve.store import ResourceStore
from dhis2w_fhir_serve.synthesize import generate_response
from fixture_project import ATTRIBUTE_COMBO_CODE_SYSTEM, ATTRIBUTE_COMBO_VALUE_SET, CAPTURE_CANONICAL

#: The golden event program's form, which this module republishes with a vocabulary declared on it.
EVENT_QUESTIONNAIRE = f"{CAPTURE_CANONICAL}/Questionnaire/EVTsupVis01"

COMBOS_EXTENSION_URL = f"{CAPTURE_CANONICAL}/StructureDefinition/d2-attribute-option-combos"
COMBO_EXTENSION_URL = f"{CAPTURE_CANONICAL}/StructureDefinition/d2-attribute-option-combo"

#: One concept the published CodeSystem really holds.
PUBLISHED_CONCEPT = "BqblOcSwGey"

#: The day a generated draft is anchored on, so its draw is a function of the seed alone.
TODAY = datetime.date(2026, 8, 8)


def _declaring_store(store: ResourceStore) -> ResourceStore:
    """The served store with the event program's form declaring the attribute-option-combo ValueSet."""
    entry = store.by_canonical(EVENT_QUESTIONNAIRE)
    assert entry is not None
    body = copy.deepcopy(entry.body)
    body["extension"] = [
        *(body.get("extension") or []),
        {"url": COMBOS_EXTENSION_URL, "valueCanonical": ATTRIBUTE_COMBO_VALUE_SET},
    ]
    declaring = entry.model_copy(update={"body": body})
    return ResourceStore(entries=(declaring, *store.entries))


def _combo_issues(issues: tuple[CaptureIssue, ...]) -> tuple[CaptureIssue, ...]:
    """Only the issues that name the attribute option combo, whichever code they carry."""
    return tuple(
        issue
        for issue in issues
        if issue.diagnostics is not None and "attribute option combo" in issue.diagnostics.lower()
    )


def _with_combo(response: dict[str, Any], coding: dict[str, Any]) -> dict[str, Any]:
    """The same submission filed under one hand-written coding."""
    body = copy.deepcopy(response)
    body["extension"] = [
        *(entry for entry in body.get("extension") or [] if entry.get("url") != COMBO_EXTENSION_URL),
        {"url": COMBO_EXTENSION_URL, "valueCoding": coding},
    ]
    return body


def _accept(
    body: dict[str, Any], indexes: CaptureIndexCache, naming: CaptureNaming, store: ResourceStore
) -> ValidatedCapture:
    """Validate one submission against a lenient facade, failing the test when it is refused."""
    return validate_response(json.dumps(body).encode(), indexes, naming, store, False)


def _refuse(
    body: dict[str, Any], indexes: CaptureIndexCache, naming: CaptureNaming, store: ResourceStore
) -> CaptureRejection:
    """Validate one submission against a strict facade, failing the test when it is accepted."""
    with pytest.raises(CaptureRejection) as raised:
        validate_response(json.dumps(body).encode(), indexes, naming, store, True)
    return raised.value


def test_the_index_reads_a_program_forms_declared_vocabulary(
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The declaration is read off `D2AttributeOptionCombos` whatever form kind carries it."""
    store = _declaring_store(capture_store)
    entry = store.by_canonical(EVENT_QUESTIONNAIRE)
    assert entry is not None

    index = build_capture_index(entry.body, capture_naming, store)

    assert index.form_kind == "event"
    assert index.attribute_option_combos is not None
    assert index.attribute_option_combos.value_set == ATTRIBUTE_COMBO_VALUE_SET
    assert index.attribute_option_combos.system == ATTRIBUTE_COMBO_CODE_SYSTEM


def test_a_generated_program_draft_draws_a_combo_from_the_declared_set(
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The draft carries the very key DHIS2 demands of the event it becomes, coded from the published pair."""
    store = _declaring_store(capture_store)
    entry = store.by_canonical(EVENT_QUESTIONNAIRE)
    assert entry is not None
    index = build_capture_index(entry.body, capture_naming, store)

    drafted = generate_response(
        Questionnaire.model_validate(entry.body), index, capture_naming, store, seed=3, today=TODAY
    )

    carried = [extension for extension in drafted.extension or [] if extension.url == COMBO_EXTENSION_URL]
    assert len(carried) == 1
    coding = carried[0].valueCoding
    assert coding is not None
    assert coding.system == ATTRIBUTE_COMBO_CODE_SYSTEM


def test_a_program_response_naming_a_published_concept_is_accepted_silently(
    event_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """A concept of the declared ValueSet is what the contract asks for, so nothing is noted."""
    store = _declaring_store(capture_store)
    body = _with_combo(event_response, {"system": ATTRIBUTE_COMBO_CODE_SYSTEM, "code": PUBLISHED_CONCEPT})

    accepted = _accept(body, capture_indexes, capture_naming, store)

    assert _combo_issues(accepted.warnings) == ()


def test_a_program_response_naming_no_combo_is_graded_as_the_data_set_path_grades_it(
    event_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """A warning on the receipt by default, naming the E1055 DHIS2 would answer the event with."""
    store = _declaring_store(capture_store)

    accepted = _accept(event_response, capture_indexes, capture_naming, store)

    noted = _combo_issues(accepted.warnings)
    assert len(noted) == 1
    assert noted[0].severity == "warning"
    assert noted[0].expression == "QuestionnaireResponse.extension"
    assert noted[0].diagnostics is not None
    assert ATTRIBUTE_COMBO_VALUE_SET in noted[0].diagnostics
    assert "E1055" in noted[0].diagnostics


def test_a_strict_facade_refuses_the_missing_combo_a_lenient_one_warns_about(
    event_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The dial that grades the third key of a data value set grades a program capture the same way."""
    store = _declaring_store(capture_store)

    rejection = _refuse(event_response, capture_indexes, capture_naming, store)

    assert rejection.http_status == 422
    refused = _combo_issues(tuple(issue for issue in rejection.issues if issue.is_error()))
    assert len(refused) == 1
    assert refused[0].diagnostics is not None
    assert "E1055" in refused[0].diagnostics


def test_a_combo_the_published_vocabulary_does_not_hold_names_the_error_dhis2_answers(
    event_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """DHIS2 answers `E1115` to an event naming a category option combo it cannot find, and so does this."""
    store = _declaring_store(capture_store)
    body = _with_combo(event_response, {"system": ATTRIBUTE_COMBO_CODE_SYSTEM, "code": "Nowhere0001"})

    accepted = _accept(body, capture_indexes, capture_naming, store)

    noted = _combo_issues(accepted.warnings)
    assert len(noted) == 1
    assert noted[0].code == "code-invalid"
    assert noted[0].diagnostics is not None
    assert "E1115" in noted[0].diagnostics


def test_a_default_combo_program_form_checks_nothing(
    event_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """A program on the default category combo declares nothing, and its responses name nothing."""
    accepted = _accept(event_response, capture_indexes, capture_naming, capture_store)

    assert _combo_issues(accepted.warnings) == ()
