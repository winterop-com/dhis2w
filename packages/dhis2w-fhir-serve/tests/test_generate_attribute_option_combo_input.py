"""`$generate`'s `attributeOptionCombo` input: the half of the capture key a client pins rather than draws.

`subject` pins where a draft reports from; this pins what it is filed under. The two are one rule in
two places - a capture UI refilling a form somebody has made a choice on names the choice, and the
draft comes back around it - and the rule only holds if what was named is never swapped. So a combo
the instance does not accept at the organisation unit, or for the period the response reports for, is
refused with which of the two closed it rather than replaced by one the draw preferred.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
from dhis2w_fhir.config import FhirProject
from dhis2w_fhir_serve.app import create_app
from dhis2w_fhir_serve.settings import ServeSettings

#: The form on the non-default category combo, and its four published combos.
ATTRIBUTE_COMBO_ID = "TuL8IOPzpHh"
COMBO_SYSTEM = "http://localhost:8080/fhir/CodeSystem/d2-aoc-idcDPkDtepR-cs"
COMBO_CONCEPTS = ("pO5CEqK6c1s", "sSeEjeQ0Rgt", "BqblOcSwGey", "oawMLLH7OjA")

#: The combo extension a generated aggregate response carries its key on.
COMBO_EXTENSION = "http://localhost:8080/fhir/StructureDefinition/d2-attribute-option-combo"

#: The two organisation units of the fixture's registry a restriction can tell apart.
ROOT_LOCATION = "ImspTQPwCqd"
DISTRICT_LOCATION = "O6uvpzGd5pu"

#: The restriction artifact one restricted category option publishes, and the property naming it.
RESTRICTION_LIST_ID = "d2-aoc-yMj2MnmNI8L-org-units"
RESTRICTION_PROPERTY = "dhis2-organisation-units"

#: The property a concept states the end of its calendar window on.
VALID_TO_PROPERTY = "dhis2-valid-to"

#: The compiled file the fixture publishes the combo vocabulary as, rewritten per test.
_CODE_SYSTEM_FILE = "CodeSystem-d2-aoc-idcDPkDtepR-cs.json"

#: Seeds a pin is asserted stable over - enough that a draw ranging wider than one answer would show.
VARIANCE_SEEDS = (1, 2, 3, 7, 42, 9999)


@asynccontextmanager
async def _serving(project: FhirProject) -> AsyncGenerator[httpx2.AsyncClient]:
    """An in-process client over one project, with the lifespan run around it."""
    app = create_app(ServeSettings(project_dir=project.project_root))
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://serve.test") as client:
            yield client


async def _generate(client: httpx2.AsyncClient, **params: str | int) -> httpx2.Response:
    """Invoke `$generate` on the combo-bearing form with whatever inputs the test names."""
    return await client.get(f"/Questionnaire/{ATTRIBUTE_COMBO_ID}/$generate", params=params)


def _drawn_combo(generated: dict[str, Any]) -> str | None:
    """The concept code one generated response is filed under, or None where it carries no combo."""
    for extension in generated.get("extension") or []:
        if extension.get("url") == COMBO_EXTENSION:
            code: str = extension["valueCoding"]["code"]
            return code
    return None


def _diagnostics(outcome: dict[str, Any]) -> str:
    """The first issue's diagnostics off an OperationOutcome body."""
    text: str = outcome["issue"][0]["diagnostics"]
    return text


def _property_declaration(code: str, kind: str) -> dict[str, Any]:
    """One CodeSystem property declaration in the shape the generator writes it."""
    return {
        "code": code,
        "uri": f"http://dhis2.org/fhir/property/{code}",
        "description": f"The {code} of a category option behind this attribute option combo.",
        "type": kind,
    }


def _scoped_code_system(
    body: dict[str, Any], scoped: dict[str, dict[str, str]], declarations: dict[str, str]
) -> dict[str, Any]:
    """The combo vocabulary with per-concept properties written on, as the generator declares them."""
    written = copy.deepcopy(body)
    written["property"] = [
        *(written.get("property") or []),
        *(_property_declaration(code, kind) for code, kind in declarations.items()),
    ]
    for concept in written.get("concept") or []:
        properties = scoped.get(concept["code"])
        if properties is None:
            continue
        concept["property"] = [
            *(concept.get("property") or []),
            *(
                {"code": code, "valueDateTime" if declarations[code] == "dateTime" else "valueString": value}
                for code, value in properties.items()
            ),
        ]
    return written


def _restriction_list(*units: str) -> dict[str, Any]:
    """One category option's restriction as the generator publishes it: a snapshot List of Locations."""
    return {
        "resourceType": "List",
        "id": RESTRICTION_LIST_ID,
        "status": "current",
        "mode": "snapshot",
        "title": "Organisation units category option yMj2MnmNI8L may be captured at",
        "entry": [{"item": {"reference": f"Location/{unit}"}} for unit in units],
    }


def _scoped_project(
    project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
    scoped: dict[str, dict[str, str]],
    declarations: dict[str, str],
    restricted_to: tuple[str, ...] = (),
) -> FhirProject:
    """The golden project with the named concepts scoped, written where the loader reads them."""
    compiled = project.ig_directory / "fsh-generated" / "resources" / _CODE_SYSTEM_FILE
    body: dict[str, Any] = json.loads(compiled.read_text(encoding="utf-8"))
    write_resource(compiled, _scoped_code_system(body, scoped, declarations))
    if restricted_to:
        write_resource(
            project.ig_directory / "input" / "resources" / "registry" / f"List-{RESTRICTION_LIST_ID}.json",
            _restriction_list(*restricted_to),
        )
    return project


async def test_a_named_combo_is_what_the_draft_is_filed_under(capture_project: FhirProject) -> None:
    """Every seed comes back keyed to the combo the caller named, which a draw over four would not."""
    async with _serving(capture_project) as client:
        drawn = {
            _drawn_combo((await _generate(client, seed=seed, attributeOptionCombo="sSeEjeQ0Rgt")).json())
            for seed in VARIANCE_SEEDS
        }

    assert drawn == {"sSeEjeQ0Rgt"}


async def test_a_named_combo_behind_its_system_names_the_same_concept(capture_project: FhirProject) -> None:
    """A client holding the whole coding sends the whole coding, which is the spelling a Coding has."""
    async with _serving(capture_project) as client:
        generated = (await _generate(client, seed=4, attributeOptionCombo=f"{COMBO_SYSTEM}|sSeEjeQ0Rgt")).json()

    assert _drawn_combo(generated) == "sSeEjeQ0Rgt"


async def test_a_named_combo_and_a_named_unit_are_both_honoured(capture_project: FhirProject) -> None:
    """The two pins are one target, and a draft that changed either would be discarding a choice."""
    async with _serving(capture_project) as client:
        generated = (
            await _generate(
                client,
                seed=11,
                subject=f"Location/{DISTRICT_LOCATION}",
                attributeOptionCombo="oawMLLH7OjA",
            )
        ).json()

    assert generated["subject"]["reference"] == f"Location/{DISTRICT_LOCATION}"
    assert _drawn_combo(generated) == "oawMLLH7OjA"


async def test_a_named_combo_is_read_off_a_posted_parameters_body(capture_project: FhirProject) -> None:
    """R4 lets a client invoke an operation with a Parameters body, so the input is read there too."""
    body = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "seed", "valueInteger": 6},
            {"name": "attributeOptionCombo", "valueString": "pO5CEqK6c1s"},
        ],
    }

    async with _serving(capture_project) as client:
        generated = (await client.post(f"/Questionnaire/{ATTRIBUTE_COMBO_ID}/$generate", json=body)).json()

    assert _drawn_combo(generated) == "pO5CEqK6c1s"


async def test_a_combo_the_form_does_not_publish_is_refused_by_name(capture_project: FhirProject) -> None:
    """Naming something the vocabulary never held is answered rather than quietly drawn over."""
    async with _serving(capture_project) as client:
        refused = await _generate(client, seed=1, attributeOptionCombo="NoSuchCombo")

    assert refused.status_code == 422
    diagnostics = _diagnostics(refused.json())
    assert "NoSuchCombo" in diagnostics
    assert f"{len(COMBO_CONCEPTS)} attribute option combo(s)" in diagnostics


async def test_a_combo_named_under_another_system_is_refused(capture_project: FhirProject) -> None:
    """A code is only a code under a system, and a system this form does not file under names nothing here."""
    async with _serving(capture_project) as client:
        refused = await _generate(client, seed=1, attributeOptionCombo="http://example.org/other|sSeEjeQ0Rgt")

    assert refused.status_code == 422
    assert "http://example.org/other" in _diagnostics(refused.json())


async def test_a_named_combo_restricted_away_from_the_named_unit_is_refused(
    capture_project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
) -> None:
    """The pair the caller asked for is one DHIS2 answers E8025, so it is said rather than drafted."""
    project = _scoped_project(
        capture_project,
        write_resource,
        {"sSeEjeQ0Rgt": {RESTRICTION_PROPERTY: f"List/{RESTRICTION_LIST_ID}"}},
        {RESTRICTION_PROPERTY: "string"},
        restricted_to=(DISTRICT_LOCATION,),
    )

    async with _serving(project) as client:
        refused = await _generate(
            client, seed=1, subject=f"Location/{ROOT_LOCATION}", attributeOptionCombo="sSeEjeQ0Rgt"
        )

    assert refused.status_code == 422
    diagnostics = _diagnostics(refused.json())
    assert "sSeEjeQ0Rgt" in diagnostics
    assert f"Location/{ROOT_LOCATION}" in diagnostics
    assert "E8025" in diagnostics


async def test_a_named_combo_restricted_elsewhere_draws_a_unit_it_may_be_filed_at(
    capture_project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
) -> None:
    """Naming only the combo leaves the unit to the draw, and the draw reads the restriction the other way."""
    project = _scoped_project(
        capture_project,
        write_resource,
        {"sSeEjeQ0Rgt": {RESTRICTION_PROPERTY: f"List/{RESTRICTION_LIST_ID}"}},
        {RESTRICTION_PROPERTY: "string"},
        restricted_to=(DISTRICT_LOCATION,),
    )

    async with _serving(project) as client:
        drawn = {
            (await _generate(client, seed=seed, attributeOptionCombo="sSeEjeQ0Rgt")).json()["subject"]["reference"]
            for seed in VARIANCE_SEEDS
        }

    assert drawn == {f"Location/{DISTRICT_LOCATION}"}


async def test_a_named_combo_closed_for_the_period_is_refused_on_the_date_axis(
    capture_project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
) -> None:
    """The two axes send a reader to two different places, so the refusal names which one closed it."""
    project = _scoped_project(
        capture_project,
        write_resource,
        {"sSeEjeQ0Rgt": {VALID_TO_PROPERTY: "2016-10-01"}},
        {VALID_TO_PROPERTY: "dateTime"},
    )

    async with _serving(project) as client:
        refused = await _generate(client, seed=1, attributeOptionCombo="sSeEjeQ0Rgt")

    assert refused.status_code == 422
    diagnostics = _diagnostics(refused.json())
    assert "sSeEjeQ0Rgt" in diagnostics
    assert "E8032" in diagnostics
    assert "E8025" not in diagnostics


async def test_a_named_combo_on_a_form_that_declares_none_is_refused(capture_project: FhirProject) -> None:
    """A form on the default category combo is keyed by the unit and the period alone, and says so."""
    async with _serving(capture_project) as client:
        refused = await client.get(
            "/Questionnaire/BfMAe6Itzgt/$generate", params={"attributeOptionCombo": "sSeEjeQ0Rgt"}
        )

    assert refused.status_code == 422
    assert "default category combo" in _diagnostics(refused.json())


async def test_a_misspelled_combo_input_is_refused_as_a_bad_request(capture_project: FhirProject) -> None:
    """A token that is not a code and not a `<system>|<code>` pair is answered here, not drawn against."""
    async with _serving(capture_project) as client:
        refused = await _generate(client, attributeOptionCombo="a|b|c")

    assert refused.status_code == 400
    assert "attributeOptionCombo" in _diagnostics(refused.json())


async def test_a_draft_filed_under_a_named_combo_posts_back(capture_project: FhirProject) -> None:
    """The round trip the whole operation stands on holds with the combo pinned as well as drawn."""
    async with _serving(capture_project) as client:
        generated = (await _generate(client, seed=8, attributeOptionCombo="oawMLLH7OjA")).json()
        posted = await client.post(
            "/QuestionnaireResponse",
            content=json.dumps(generated).encode(),
            headers={"Content-Type": "application/fhir+json"},
        )

    assert posted.status_code == 201
