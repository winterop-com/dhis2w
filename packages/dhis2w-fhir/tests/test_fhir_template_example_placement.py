"""Every bundled template's own examples are captures the DHIS2 demo instance would accept.

A template's `ig/input/` is a build artifact that happens to be committed, and its examples are the
first thing anybody POSTs: `d2w fhir init --template` lays the tree down, `d2w fhir serve` serves it,
and a reader copies one example into their own client. So an example reporting from an organisation
unit its own form is not assigned to, keyed to an attribute option combo DHIS2 scopes away from that
organisation unit, or keyed to one DHIS2 closed before the period it reports for, is a template that
teaches a capture the instance refuses - `E1029` on the assignment axis, `E8025` on the combo's unit
axis, `E8032` on its date axis.

A tracker corpus has a third rule of the same kind: a stage example answers one enrollment, and only
a registration example of the same template creates one. DHIS2 refuses an event naming an enrollment
nothing creates with `E1313`, and the program mismatch behind it with `E1079`. And the capture page
is the one place in a guide that teaches a reader to build a capture by hand, so the organisation
unit it quotes is graded exactly as an example's is.

Regenerating a payload needs a DHIS2 instance; catching one that drifted must not. Every fact is
published in the payload itself - the form's assignment List, one restriction List per restricted
category option of the combo vocabulary, the window each combo concept carries, and the enrollment
each example names - so this reads the shipped bytes and needs no connection. `projects/README.md`
says how to regenerate when it fails.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from dhis2w_fhir.resources.attribute_combos.restrictions import (
    ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
    ATTRIBUTE_OPTION_VALID_FROM_PROPERTY,
    ATTRIBUTE_OPTION_VALID_TO_PROPERTY,
    CategoryOptionValidity,
)
from dhis2w_fhir.resources.attribute_combos.schemas import ATTRIBUTE_COMBO_DIRECTORY
from dhis2w_fhir.resources.questionnaires.assignments import ASSIGNMENT_DIRECTORY
from dhis2w_fhir.scaffold.project_templates import TemplateOrigin, list_templates

#: The templates that ride the wheel. The checkout-only ones commit no generated tree to grade.
BUNDLED = [template for template in list_templates() if template.origin is TemplateOrigin.BUNDLED]

#: Where a template keeps the forms it publishes, one directory per DHIS2 object kind.
_FORM_DIRECTORIES = ("data-sets", "event-programs", "tracker-programs", "tracked-entity-types")

#: The two elements a QuestionnaireResponse names its capture organisation unit on: an aggregate and an
#: event response carry it as the response's own subject, a tracker one as the D2OrganisationUnit extension.
_EXAMPLE_ORGANISATION_UNIT = re.compile(
    r"^\* (?:subject|extension\[D2OrganisationUnit\]\.valueReference) = Reference\((?P<reference>[^)\s]+)\)$",
    re.MULTILINE,
)

#: The combo one example is filed under, as the coding the vocabulary publishes it under.
_EXAMPLE_COMBO = re.compile(
    r"^\* extension\[D2AttributeOptionCombo\]\.valueCoding = (?P<vocabulary>\S+)#(?P<code>\S+)", re.MULTILINE
)

#: The assignment List and the combo vocabulary a Questionnaire declares.
_FORM_ASSIGNMENT = re.compile(
    r"^\* extension\[D2OrganisationUnitAssignment\]\.valueReference = Reference\((?P<list>[^)\s]+)\)$", re.MULTILINE
)
_FORM_VOCABULARY = re.compile(
    r"^\* extension\[D2AttributeOptionCombos\]\.valueCanonical = Canonical\((?P<value_set>[^)\s]+)\)$", re.MULTILINE
)


def _payload_root(name: str) -> Path:
    """The committed `ig/input/` tree of one bundled template."""
    return Path(__file__).resolve().parents[1] / "src/dhis2w_fhir/scaffold/projects" / name / "ig/input"


def _documents(directory: Path) -> list[dict[str, Any]]:
    """Every JSON resource one payload directory holds, in file-name order."""
    if not directory.is_dir():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


def _list_members(documents: list[dict[str, Any]]) -> dict[str, set[str]]:
    """The references each published List holds, keyed by `List/<id>` the way a form names one."""
    return {
        f"List/{document['id']}": {entry["item"]["reference"] for entry in document.get("entry") or []}
        for document in documents
        if document.get("resourceType") == "List"
    }


def _concept_restrictions(documents: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    """The restriction Lists each combo concept names, keyed by the CodeSystem FSH name and the concept code."""
    restrictions: dict[tuple[str, str], list[str]] = {}
    for document in documents:
        if document.get("resourceType") != "CodeSystem":
            continue
        for concept in document.get("concept") or []:
            restrictions[document["name"], concept["code"]] = [
                entry["valueString"]
                for entry in concept.get("property") or []
                if entry["code"] == ATTRIBUTE_OPTION_RESTRICTION_PROPERTY
            ]
    return restrictions


def _form_sources(root: Path) -> dict[str, str]:
    """The FSH of every form one template publishes, by the DHIS2 UID its file is named after.

    Read to the bottom of each directory, because the tracker target nests: a stage sits at
    `tracker-programs/<program uid>/<stage uid>.fsh`, and a stage is a form like any other.
    """
    return {
        path.stem: path.read_text(encoding="utf-8")
        for directory in _FORM_DIRECTORIES
        for path in sorted((root / "fsh" / directory).rglob("*.fsh"))
    }


@pytest.mark.parametrize("template", BUNDLED, ids=lambda template: template.name)
def test_every_bundled_example_reports_from_a_unit_its_form_is_assigned_to(template: Any) -> None:  # noqa: ANN401
    """DHIS2 refuses a capture outside the form's assignment with E1029, so no shipped example is outside one."""
    root = _payload_root(template.name)
    assignments = _list_members(_documents(root / "resources" / ASSIGNMENT_DIRECTORY))
    forms = _form_sources(root)
    checked = 0
    for path in sorted((root / "fsh/examples").glob("*.fsh")):
        example = path.read_text(encoding="utf-8")
        form_uid = path.stem.rsplit("-", 1)[0]
        declared = _FORM_ASSIGNMENT.search(forms.get(form_uid, ""))
        unit = _EXAMPLE_ORGANISATION_UNIT.search(example)
        if declared is None or unit is None:
            continue
        members = assignments[declared.group("list")]
        assert unit.group("reference") in members, (
            f"{template.name}: {path.name} reports from {unit.group('reference')}, "
            f"which {declared.group('list')} does not hold"
        )
        checked += 1
    assert checked, f"{template.name} publishes no example against an assigned form"


@pytest.mark.parametrize("template", BUNDLED, ids=lambda template: template.name)
def test_every_bundled_example_is_keyed_to_a_combo_usable_at_its_own_unit(template: Any) -> None:  # noqa: ANN401
    """DHIS2 refuses a capture keyed to a combo scoped away from its organisation unit with E8025."""
    root = _payload_root(template.name)
    combos = _documents(root / "resources" / ATTRIBUTE_COMBO_DIRECTORY)
    restrictions = _concept_restrictions(combos)
    members = _list_members(combos)
    checked = 0
    for path in sorted((root / "fsh/examples").glob("*.fsh")):
        example = path.read_text(encoding="utf-8")
        combo = _EXAMPLE_COMBO.search(example)
        unit = _EXAMPLE_ORGANISATION_UNIT.search(example)
        if combo is None or unit is None:
            continue
        vocabulary = combo.group("vocabulary").removeprefix("$")
        for reference in restrictions[vocabulary, combo.group("code")]:
            assert unit.group("reference") in members[reference], (
                f"{template.name}: {path.name} is keyed to {combo.group('code')} at "
                f"{unit.group('reference')}, which {reference} does not hold"
            )
        checked += 1
    assert checked, f"{template.name} publishes no example on a non-default category combo"


#: The reporting period one aggregate example carries, as the D2Period extension states its two ends.
_EXAMPLE_PERIOD = re.compile(
    r'^\* extension\[D2Period\]\.extension\[period\]\.valuePeriod\.start = "(?P<start>[^"]+)"$\n'
    r'^\* extension\[D2Period\]\.extension\[period\]\.valuePeriod\.end = "(?P<end>[^"]+)"$',
    re.MULTILINE,
)


def _concept_windows(documents: list[dict[str, Any]]) -> dict[tuple[str, str], CategoryOptionValidity]:
    """The window each combo concept is open for, keyed by the CodeSystem FSH name and the concept code."""
    windows: dict[tuple[str, str], CategoryOptionValidity] = {}
    for document in documents:
        if document.get("resourceType") != "CodeSystem":
            continue
        for concept in document.get("concept") or []:
            stated = {
                entry["code"]: entry["valueDateTime"]
                for entry in concept.get("property") or []
                if entry["code"] in {ATTRIBUTE_OPTION_VALID_FROM_PROPERTY, ATTRIBUTE_OPTION_VALID_TO_PROPERTY}
            }
            windows[document["name"], concept["code"]] = CategoryOptionValidity(
                valid_from=_day(stated.get(ATTRIBUTE_OPTION_VALID_FROM_PROPERTY)),
                valid_to=_day(stated.get(ATTRIBUTE_OPTION_VALID_TO_PROPERTY)),
            )
    return windows


def _day(value: str | None) -> date | None:
    """One published `dateTime` as the calendar day DHIS2 scopes a category option by."""
    return None if value is None else date.fromisoformat(value[:10])


@pytest.mark.parametrize("template", BUNDLED, ids=lambda template: template.name)
def test_every_bundled_example_is_keyed_to_a_combo_open_for_its_own_period(template: Any) -> None:  # noqa: ANN401
    """DHIS2 refuses a capture whose combo window does not cover the whole period it reports for, with E8032."""
    root = _payload_root(template.name)
    windows = _concept_windows(_documents(root / "resources" / ATTRIBUTE_COMBO_DIRECTORY))
    checked = 0
    for path in sorted((root / "fsh/examples").glob("*.fsh")):
        example = path.read_text(encoding="utf-8")
        combo = _EXAMPLE_COMBO.search(example)
        period = _EXAMPLE_PERIOD.search(example)
        if combo is None or period is None:
            continue
        window = windows[combo.group("vocabulary").removeprefix("$"), combo.group("code")]
        start, end = date.fromisoformat(period.group("start")), date.fromisoformat(period.group("end"))
        assert window.covers(start, end), (
            f"{template.name}: {path.name} is keyed to {combo.group('code')} for {start} to {end}, "
            f"which its window does not cover"
        )
        checked += 1
    assert checked, f"{template.name} publishes no aggregate example on a non-default category combo"


#: The enrollment a tracker example names, and the tracked entity it belongs to. A registration example
#: creates the pair; a stage example answers into one the same template created, or into nothing at all.
_EXAMPLE_ENROLLMENT = re.compile(
    r'^\* extension\[D2TrackerEnrollment\]\.valueIdentifier\.value = "(?P<enrollment>[^"]+)"$', re.MULTILINE
)

#: What kind of DHIS2 form one example answers, as the response's own D2FormType code states it.
_EXAMPLE_FORM_TYPE = re.compile(r"^\* extension\[D2FormType\]\.valueCode = #(?P<kind>\S+)$", re.MULTILINE)

#: The organisation unit the capture page works its aggregate steps against, in the snippet a reader copies.
_CAPTURE_PAGE_SUBJECT = re.compile(r'^"subject": \{ "reference": "(?P<reference>[^"]+)" \}$', re.MULTILINE)

#: The organisation unit the tracker walk-through works against, which rides the D2OrganisationUnit
#: extension rather than the response's subject - a tracker response's subject is the tracked entity.
_CAPTURE_PAGE_TRACKER_UNIT = re.compile(
    r'^  "valueReference": \{ "reference": "(?P<reference>[^"]+)" \}$', re.MULTILINE
)

#: The DHIS2 UID of each form the capture page works a walk-through against, one per section.
_CAPTURE_PAGE_FORM = re.compile(r"^The steps are worked against \*\*.+\*\* \(`(?P<uid>[^`]+)`\)\.$", re.MULTILINE)

#: Where the tracker walk-through starts, which is what separates its quoted unit from the aggregate one.
_CAPTURE_PAGE_TRACKER_HEADING = "## A tracker event response, step by step"


def _examples_by_kind(root: Path) -> dict[str, list[str]]:
    """Every published example's FSH, grouped by the DHIS2 form kind its D2FormType states."""
    grouped: dict[str, list[str]] = {}
    for path in sorted((root / "fsh/examples").glob("*.fsh")):
        example = path.read_text(encoding="utf-8")
        kind = _EXAMPLE_FORM_TYPE.search(example)
        if kind is not None:
            grouped.setdefault(kind.group("kind"), []).append(example)
    return grouped


@pytest.mark.parametrize("template", BUNDLED, ids=lambda template: template.name)
def test_every_bundled_stage_example_answers_an_enrollment_a_registration_example_creates(
    template: Any,  # noqa: ANN401
) -> None:
    """DHIS2 refuses an event naming an enrollment nothing creates with E1313, and the program with E1079."""
    grouped = _examples_by_kind(_payload_root(template.name))
    created = {
        match.group("enrollment")
        for example in grouped.get("tracker", [])
        if (match := _EXAMPLE_ENROLLMENT.search(example)) is not None
    }
    checked = 0
    for example in grouped.get("tracker-event", []):
        answered = _EXAMPLE_ENROLLMENT.search(example)
        assert answered is not None, f"{template.name}: a stage example names no enrollment at all"
        assert answered.group("enrollment") in created, (
            f"{template.name}: a stage example answers enrollment {answered.group('enrollment')}, "
            f"which no registration example of this template creates"
        )
        checked += 1
    if grouped.get("tracker-event"):
        assert checked, f"{template.name} publishes no stage example to grade"


@pytest.mark.parametrize("template", BUNDLED, ids=lambda template: template.name)
def test_the_capture_page_of_every_bundled_template_teaches_an_assigned_organisation_unit(
    template: Any,  # noqa: ANN401
) -> None:
    """The page is where a reader is taught to build a capture, so the unit it quotes is one DHIS2 admits."""
    root = _payload_root(template.name)
    page = (root / "pagecontent/capture.md").read_text(encoding="utf-8")
    worked_form = _CAPTURE_PAGE_FORM.search(page)
    subject = _CAPTURE_PAGE_SUBJECT.search(page)
    assert worked_form is not None, f"{template.name}: capture.md works no form through the aggregate steps"
    assert subject is not None, f"{template.name}: capture.md quotes no subject for a reader to copy"
    _assert_quoted_unit_is_assigned(template.name, root, worked_form.group("uid"), subject.group("reference"))


@pytest.mark.parametrize("template", BUNDLED, ids=lambda template: template.name)
def test_the_capture_page_of_every_bundled_template_teaches_an_assigned_unit_for_its_tracker_stage_too(
    template: Any,  # noqa: ANN401
) -> None:
    """The tracker walk-through is a second form and a second assignment, and it is copied just as readily.

    A tracker stage is assigned through its program, so the List the quoted unit is graded against is
    the one the stage's own Questionnaire declares. A template whose tracker stage has no unit to
    quote states the fact instead, and states no organisation unit at all - which is what leaves this
    with nothing to grade rather than something wrong to grade.
    """
    root = _payload_root(template.name)
    page = (root / "pagecontent/capture.md").read_text(encoding="utf-8")
    if _CAPTURE_PAGE_TRACKER_HEADING not in page:
        pytest.skip(f"{template.name} publishes no tracker program stage")
    section = page.split(_CAPTURE_PAGE_TRACKER_HEADING, 1)[1]
    unit = _CAPTURE_PAGE_TRACKER_UNIT.search(section)
    if unit is None:
        return
    worked_form = _CAPTURE_PAGE_FORM.search(section)
    assert worked_form is not None, f"{template.name}: capture.md quotes a unit for a stage it names nowhere"
    _assert_quoted_unit_is_assigned(template.name, root, worked_form.group("uid"), unit.group("reference"))


def _assert_quoted_unit_is_assigned(name: str, root: Path, form_uid: str, reference: str) -> None:
    """One organisation unit the capture page quotes, graded against the assignment List its form declares."""
    declared = _FORM_ASSIGNMENT.search(_form_sources(root).get(form_uid, ""))
    assert declared is not None, f"{name}: the worked form {form_uid} declares no assignment List"
    members = _list_members(_documents(root / "resources" / ASSIGNMENT_DIRECTORY))[declared.group("list")]
    assert reference in members, (
        f"{name}: capture.md files from {reference}, which {declared.group('list')} does not hold"
    )
