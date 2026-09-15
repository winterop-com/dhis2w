"""The bundled template payloads are what today's generator writes, checked without an instance.

A template's `ig/input/` is a build artifact that happens to be committed: `d2w fhir generate` wrote
it against a DHIS2 demo instance on the day it ran, and the emitters move underneath it. Nothing
else in the suite reads those files, so a generator change lands, every test passes, and three
templates go on laying down a tree the current code would never produce - a pristine `make sushi`
and a regenerated one publishing different content, with the selection beside them still claiming
the tree matches.

Regenerating needs a DHIS2 instance; catching the drift must not. So these tests emit one Location
from a fixture organisation unit with today's emitter and hold every bundled Location to the shape
it produces: the profile it claims, the identifier slices it carries, the translated name element,
and the level extension that closes it. `projects/README.md` says how to regenerate when one fails.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from dhis2w_fhir.attributes import AttributeCodeIndex
from dhis2w_fhir.config import GenerateConfig
from dhis2w_fhir.i18n import TranslationIn
from dhis2w_fhir.resources.organisation_units import build_organisation_unit_instances
from dhis2w_fhir.resources.organisation_units.schemas import (
    OrganisationUnitIn,
    OrganisationUnitLevelIn,
    OrganisationUnitLevelNames,
)
from dhis2w_fhir.scaffold.project_templates import TemplateOrigin, list_templates
from pydantic import BaseModel, ConfigDict

#: The templates that ride the wheel, by name, each with the canonical its payload states throughout.
#: The checkout-only ones commit no generated tree at all, so there is nothing of theirs to grade.
BUNDLED = {template.name: template for template in list_templates() if template.origin is TemplateOrigin.BUNDLED}

#: Where a template keeps the organisation-unit registry its selection produced.
REGISTRY_RELATIVE_PATH = Path("ig/input/resources/registry")

#: The FHIR extension a translated element carries, one per translation.
TRANSLATION_EXTENSION_URL = "http://hl7.org/fhir/StructureDefinition/translation"

#: A district and the facility under it, one of which is translated - the shape a real registry holds.
_DISTRICT = OrganisationUnitIn(
    uid="PMa2VCrupOd",
    name="Kambia",
    level=2,
    path="/ImspTQPwCqd/PMa2VCrupOd",
    code="OU_226225",
)
_FACILITY = OrganisationUnitIn(
    uid="xGMGhjA3y6J",
    name="Mambolo",
    level=3,
    path="/ImspTQPwCqd/PMa2VCrupOd/xGMGhjA3y6J",
    parent_uid="PMa2VCrupOd",
    code="OU_211262",
    latitude=8.884111,
    longitude=-13.022958,
    translations=[TranslationIn(locale="en-GB", property="NAME", value="Mambolo")],
)

#: What the demo instance calls the depths of its hierarchy, so the level concept carries a display.
_LEVEL_NAMES = OrganisationUnitLevelNames(
    levels=[
        OrganisationUnitLevelIn(level=1, name="National", uid="Ol1aaaaaaaa"),
        OrganisationUnitLevelIn(level=2, name="District", uid="Ol2aaaaaaaa"),
        OrganisationUnitLevelIn(level=3, name="Chiefdom", uid="Ol3aaaaaaaa"),
        OrganisationUnitLevelIn(level=4, name="Facility", uid="Ol4aaaaaaaa"),
    ]
)


def _emitted_location(canonical: str) -> dict[str, Any]:
    """The Location today's emitter writes for the translated fixture facility, under one canonical."""
    build = build_organisation_unit_instances(
        [_DISTRICT, _FACILITY],
        GenerateConfig(),
        canonical,
        attribute_codes=AttributeCodeIndex(),
        level_names=_LEVEL_NAMES,
    )
    documents: dict[str, dict[str, Any]] = {
        artifact.relative_path: json.loads(artifact.content) for artifact in build.artifacts
    }
    return documents[f"registry/Location-{_FACILITY.uid}.json"]


def _bundled_locations(name: str) -> list[dict[str, Any]]:
    """Every Location the named template lays down, parsed."""
    registry = BUNDLED[name].root / REGISTRY_RELATIVE_PATH
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(registry.glob("Location-*.json"))]


def _translation_shape(element: dict[str, Any]) -> list[list[str]]:
    """The urls one translated element states, which is the part a payload and an emitter must share."""
    return [[part["url"] for part in extension["extension"]] for extension in element["extension"]]


@pytest.fixture(params=sorted(BUNDLED))
def template_name(request: pytest.FixtureRequest) -> str:
    """Each bundled template in turn, so a failure names the one that needs regenerating."""
    return str(request.param)


def test_the_selection_and_the_payload_are_both_there(template_name: str) -> None:
    """A template is a selection plus the tree that selection produced; neither half stands alone."""
    root = BUNDLED[template_name].root

    assert (root / "selection.toml").is_file()
    assert list((root / REGISTRY_RELATIVE_PATH).glob("Location-*.json")) != []


def test_every_bundled_location_claims_the_profile_the_emitter_writes(template_name: str) -> None:
    """A payload naming a profile the guide no longer publishes is a tree SUSHI compiles into nothing."""
    canonical = BUNDLED[template_name].canonical
    expected = _emitted_location(canonical)["meta"]["profile"]

    for document in _bundled_locations(template_name):
        assert document["meta"]["profile"] == expected, document["id"]


def test_every_bundled_location_carries_the_identifier_slices_the_emitter_writes(template_name: str) -> None:
    """The DHIS2 id and code travel as identifiers, and a consumer searches on those systems by name."""
    emitted = _emitted_location(BUNDLED[template_name].canonical)
    expected = [identifier["system"] for identifier in emitted["identifier"]]

    for document in _bundled_locations(template_name):
        assert [identifier["system"] for identifier in document["identifier"]] == expected, document["id"]


def test_every_bundled_location_closes_with_the_level_extension_the_emitter_writes(template_name: str) -> None:
    """The level extension closes the list, and its coding is drawn from the guide's own level CodeSystem."""
    canonical = BUNDLED[template_name].canonical
    emitted = _emitted_location(canonical)["extension"][-1]

    for document in _bundled_locations(template_name):
        level = document["extension"][-1]
        assert level["url"] == emitted["url"], document["id"]
        assert level["valueCoding"]["system"] == emitted["valueCoding"]["system"], document["id"]
        assert level["valueCoding"]["code"].startswith("level-"), document["id"]


def test_a_translated_bundled_location_states_its_name_the_way_the_emitter_does(template_name: str) -> None:
    """The `_name` translation element is the shape a stale payload loses, so it is the one asserted by name.

    An organisation unit the instance holds a name translation for publishes that translation on the
    Location's `_name`, and every consumer reading a guide in a second language reads it there. A
    payload generated before the emitter wrote it carries none at all - which is exactly the drift
    this file exists to catch, and it is invisible to every other test in the suite.
    """
    emitted = _emitted_location(BUNDLED[template_name].canonical)
    translated = [document for document in _bundled_locations(template_name) if "_name" in document]

    assert translated != [], "no bundled Location carries the translated name today's emitter writes"
    for document in translated:
        assert _translation_shape(document["_name"]) == _translation_shape(emitted["_name"]), document["id"]
        assert [extension["url"] for extension in document["_name"]["extension"]] == [TRANSLATION_EXTENSION_URL]


def test_every_selection_names_uids_in_the_shape_dhis2_gives_them() -> None:
    """A selection is UIDs alone, and a typo there is a template that publishes something else entirely."""
    for name in sorted(BUNDLED):
        selection = tomllib.loads((BUNDLED[name].root / "selection.toml").read_text(encoding="utf-8"))
        tables = selection["generate"]
        named = [
            uid
            for table in ("data_sets", "event_programs", "tracker_programs", "option_sets", "categories")
            for uid in tables.get(table, {}).get("include_ids", [])
        ]
        named.append(tables["organisation_units"]["root"])

        assert named != [], name
        for uid in named:
            assert len(uid) == 11 and uid[0].isalpha() and uid.isalnum(), f"{name}: {uid}"


#: Where a template keeps the attribute-option-combo vocabularies its selection produced.
ATTRIBUTE_COMBO_RELATIVE_PATH = Path("ig/input/resources/attribute-option-combos")

#: Where a template keeps the narrative pages its selection produced.
PAGECONTENT_RELATIVE_PATH = Path("ig/input/pagecontent")

#: The concept properties a combination concept states its restrictions and its calendar window on.
_RESTRICTION_PROPERTY = "dhis2-organisation-units"
_VALID_FROM_PROPERTY = "dhis2-valid-from"
_VALID_TO_PROPERTY = "dhis2-valid-to"

#: What the capture page's aggregate walk-through states, read back off the markdown it wrote.
_WORKED_UNIT = re.compile(r'"subject": \{ "reference": "(?:.*/)?Location/(?P<uid>[^"/]+)" \}')
_WORKED_PERIOD = re.compile(r'"valuePeriod": \{ "start": "(?P<start>[^"]+)", "end": "(?P<end>[^"]+)" \}')
_WORKED_COMBO = re.compile(
    r'"system": "(?P<system>[^"]+)",\s*\n\s*"code": "(?P<code>[^"]+)"',
)


class _WorkedCapture(BaseModel):
    """What one template's `capture.md` teaches a client to send, read back off the page it wrote."""

    model_config = ConfigDict(frozen=True)

    organisation_unit_uid: str
    start_date: str
    end_date: str
    combo_system: str
    combo_code: str


def _worked_capture(name: str) -> _WorkedCapture | None:
    """The aggregate walk-through of one bundled template, or None where its form states no combination."""
    page = (BUNDLED[name].root / PAGECONTENT_RELATIVE_PATH / "capture.md").read_text(encoding="utf-8")
    combo = _WORKED_COMBO.search(page)
    unit = _WORKED_UNIT.search(page)
    period = _WORKED_PERIOD.search(page)
    if combo is None or unit is None or period is None:
        return None
    return _WorkedCapture(
        organisation_unit_uid=unit.group("uid"),
        start_date=period.group("start"),
        end_date=period.group("end"),
        combo_system=combo.group("system"),
        combo_code=combo.group("code"),
    )


def _combo_concept(name: str, system: str, code: str) -> dict[str, Any] | None:
    """One concept of one published attribute-option-combo CodeSystem, by the canonical the page names."""
    for path in sorted((BUNDLED[name].root / ATTRIBUTE_COMBO_RELATIVE_PATH).glob("CodeSystem-*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("url") != system:
            continue
        return next((concept for concept in document.get("concept", []) if concept.get("code") == code), None)
    return None


def _concept_property(concept: dict[str, Any], code: str) -> str | None:
    """One concept property's value, whichever `value[x]` element the property declares it on."""
    for entry in concept.get("property", []):
        if entry.get("code") == code:
            value = entry.get("valueString") or entry.get("valueDateTime") or entry.get("valueCode")
            return str(value) if value is not None else None
    return None


def _list_members(name: str, reference: str) -> set[str]:
    """The organisation units one restriction List names, by the id its entries reference them as."""
    list_id = reference.rsplit("/", 1)[-1]
    path = BUNDLED[name].root / ATTRIBUTE_COMBO_RELATIVE_PATH / f"List-{list_id}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(entry["item"]["reference"]).rsplit("/", 1)[-1]
        for entry in document.get("entry", [])
        if isinstance(entry.get("item"), dict)
    }


def test_the_capture_walkthrough_quotes_a_combination_usable_where_and_when_it_reports(template_name: str) -> None:
    """A walk-through teaching a capture DHIS2 refuses is worse than one that teaches nothing.

    DHIS2 grades an attribute option combination on two axes beyond the vocabulary itself: it scopes
    a category option to organisation units and refuses a capture filed elsewhere with `E8025`, and
    it opens the option for a calendar window and refuses a capture whose whole reporting period the
    window does not cover with `E8032`. The page states an organisation unit, a period and a
    combination in one worked snippet, so all three have to agree in the payload as committed.
    """
    worked = _worked_capture(template_name)
    if worked is None:
        pytest.skip(f"{template_name} works an aggregate form that rides the default category combination")
    concept = _combo_concept(template_name, worked.combo_system, worked.combo_code)
    assert concept is not None, f"{template_name}: capture.md quotes a concept no published CodeSystem holds"

    valid_from = _concept_property(concept, _VALID_FROM_PROPERTY)
    valid_to = _concept_property(concept, _VALID_TO_PROPERTY)
    assert valid_from is None or valid_from <= worked.start_date
    assert valid_to is None or valid_to >= worked.end_date

    restriction = _concept_property(concept, _RESTRICTION_PROPERTY)
    if restriction is not None:
        assert worked.organisation_unit_uid in _list_members(template_name, restriction)
