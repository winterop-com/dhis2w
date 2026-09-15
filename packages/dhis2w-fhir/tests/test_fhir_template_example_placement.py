"""Every bundled template's own examples are captures the DHIS2 demo instance would accept.

A template's `ig/input/` is a build artifact that happens to be committed, and its examples are the
first thing anybody POSTs: `d2w fhir init --template` lays the tree down, `d2w fhir serve` serves it,
and a reader copies one example into their own client. So an example reporting from an organisation
unit its own form is not assigned to, or keyed to an attribute option combo DHIS2 scopes away from
that organisation unit, is a template that teaches a capture the instance refuses - `E1029` on the
assignment axis, `E8025` on the combo axis.

A tracker corpus has a third rule of the same kind: a stage example answers one enrollment, and only
a registration example of the same template creates one. DHIS2 refuses an event naming an enrollment
nothing creates with `E1313`, and the program mismatch behind it with `E1079`. And the capture page
is the one place in a guide that teaches a reader to build a capture by hand, so the organisation
unit it quotes is graded exactly as an example's is.

Regenerating a payload needs a DHIS2 instance; catching one that drifted must not. Every fact is
published in the payload itself - the form's assignment List, one restriction List per restricted
category option of the combo vocabulary, and the enrollment each example names - so this reads the
shipped bytes and needs no connection. `projects/README.md` says how to regenerate when it fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from dhis2w_fhir.resources.attribute_combos.restrictions import ATTRIBUTE_OPTION_RESTRICTION_PROPERTY
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
    """The FSH of every form one template publishes, by the DHIS2 UID its file is named after."""
    return {
        path.stem: path.read_text(encoding="utf-8")
        for directory in _FORM_DIRECTORIES
        for path in sorted((root / "fsh" / directory).glob("*.fsh"))
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


#: The enrollment a tracker example names, and the tracked entity it belongs to. A registration example
#: creates the pair; a stage example answers into one the same template created, or into nothing at all.
_EXAMPLE_ENROLLMENT = re.compile(
    r'^\* extension\[D2TrackerEnrollment\]\.valueIdentifier\.value = "(?P<enrollment>[^"]+)"$', re.MULTILINE
)

#: What kind of DHIS2 form one example answers, as the response's own D2FormType code states it.
_EXAMPLE_FORM_TYPE = re.compile(r"^\* extension\[D2FormType\]\.valueCode = #(?P<kind>\S+)$", re.MULTILINE)

#: The organisation unit the capture page works its aggregate steps against, in the snippet a reader copies.
_CAPTURE_PAGE_SUBJECT = re.compile(r'^"subject": \{ "reference": "(?P<reference>[^"]+)" \}$', re.MULTILINE)

#: The DHIS2 UID of the form the capture page's aggregate walk-through is worked against.
_CAPTURE_PAGE_FORM = re.compile(r"^The steps are worked against \*\*.+\*\* \(`(?P<uid>[^`]+)`\)\.$", re.MULTILINE)


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
    declared = _FORM_ASSIGNMENT.search(_form_sources(root).get(worked_form.group("uid"), ""))
    assert declared is not None, f"{template.name}: the worked form declares no assignment List"
    members = _list_members(_documents(root / "resources" / ASSIGNMENT_DIRECTORY))[declared.group("list")]
    assert subject.group("reference") in members, (
        f"{template.name}: capture.md files from {subject.group('reference')}, which "
        f"{declared.group('list')} does not hold"
    )
