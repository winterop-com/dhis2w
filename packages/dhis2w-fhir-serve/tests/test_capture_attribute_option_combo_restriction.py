"""The organisation units an attribute option combo may be captured at, on both halves of the rule.

DHIS2 scopes a category option to organisation units and refuses a value keyed to a combo not usable
at the unit it is filed from (`E8025`). The vocabulary publishes that scope - one restriction List
per restricted category option, named from every concept met from it - and the facade reads it in
both directions: `$generate` draws a combo usable at the unit it drew, and a received response
naming one that is not is graded exactly as an organisation unit outside the form's assignment is.

The fixture's own combo vocabulary is the dhis2w-fhir golden, restricted per test, so what is being
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
from dhis2w_fhir.config import FhirProject, load_fhir_config
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
from dhis2w_fhir_serve.store import ResourceStore, StoreEntry
from fixture_project import ATTRIBUTE_COMBO_CODE_SYSTEM

#: The form on the non-default category combo, and the concept its golden response is filed under.
ATTRIBUTE_COMBO_ID = "TuL8IOPzpHh"
FILED_CONCEPT = "oawMLLH7OjA"

#: Where that golden response reports from, and the unit beneath it a restriction can single out.
ROOT_LOCATION = "ImspTQPwCqd"
DISTRICT_LOCATION = "O6uvpzGd5pu"

#: The restriction artifact one restricted category option publishes, in the shape the generator writes it.
RESTRICTION_LIST_ID = "d2-aoc-yMj2MnmNI8L-org-units"
RESTRICTION_PROPERTY = "dhis2-organisation-units"

#: The compiled file the fixture publishes the combo vocabulary as, rewritten per test.
_CODE_SYSTEM_FILE = "CodeSystem-d2-aoc-idcDPkDtepR-cs.json"

#: Seeds a draw is asserted stable over - enough that a draw ranging wider than one answer shows it.
VARIANCE_SEEDS = (1, 2, 3, 7, 42, 9999)


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


def _restricted_code_system(body: dict[str, Any], *concept_codes: str) -> dict[str, Any]:
    """The combo vocabulary with a restriction property on each named concept, declared as the generator does."""
    restricted = copy.deepcopy(body)
    restricted["property"] = [
        *(restricted.get("property") or []),
        {
            "code": RESTRICTION_PROPERTY,
            "uri": f"http://dhis2.org/fhir/property/{RESTRICTION_PROPERTY}",
            "description": "List of the organisation units a category option of this combo is restricted to.",
            "type": "string",
        },
    ]
    for concept in restricted.get("concept") or []:
        if concept["code"] not in concept_codes:
            continue
        concept["property"] = [
            *(concept.get("property") or []),
            {"code": RESTRICTION_PROPERTY, "valueString": f"List/{RESTRICTION_LIST_ID}"},
        ]
    return restricted


def _restricted_store(
    store: ResourceStore, *units: str, concept_codes: tuple[str, ...] = (FILED_CONCEPT,)
) -> ResourceStore:
    """The golden store with the named concepts restricted to `units`."""
    entries: list[StoreEntry] = []
    for entry in store.entries:
        if entry.canonical_url == ATTRIBUTE_COMBO_CODE_SYSTEM:
            entries.append(entry.model_copy(update={"body": _restricted_code_system(entry.body, *concept_codes)}))
            continue
        entries.append(entry)
    entries.append(
        StoreEntry(
            resource_type="List",
            resource_id=RESTRICTION_LIST_ID,
            source="test",
            body=_restriction_list(*units),
        )
    )
    return ResourceStore(entries=tuple(entries))


def _restricted_project(
    project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
    *units: str,
) -> FhirProject:
    """The golden project with every combo concept restricted to `units`, written where the loader reads them."""
    compiled = project.ig_directory / "fsh-generated" / "resources" / _CODE_SYSTEM_FILE
    body: dict[str, Any] = json.loads(compiled.read_text(encoding="utf-8"))
    codes = tuple(concept["code"] for concept in body.get("concept") or [])
    write_resource(compiled, _restricted_code_system(body, *codes))
    write_resource(
        project.ig_directory / "input" / "resources" / "registry" / f"List-{RESTRICTION_LIST_ID}.json",
        _restriction_list(*units),
    )
    return project


def _accept(
    body: dict[str, Any],
    indexes: CaptureIndexCache,
    naming: CaptureNaming,
    store: ResourceStore,
    strict_codes: bool = False,
) -> ValidatedCapture:
    """Validate one submission, failing the test when it is refused."""
    return validate_response(json.dumps(body).encode(), indexes, naming, store, strict_codes)


def _restriction_issues(issues: tuple[CaptureIssue, ...]) -> tuple[CaptureIssue, ...]:
    """Only the issues the organisation-unit restriction raised."""
    return tuple(
        issue
        for issue in issues
        if issue.diagnostics is not None and "organisation-unit restriction" in issue.diagnostics
    )


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


def test_a_combo_restricted_to_the_reported_unit_is_silent(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The restriction admits the unit the golden reports from, so the capture carries no finding."""
    store = _restricted_store(capture_store, ROOT_LOCATION)

    accepted = _accept(attribute_combo_response, capture_indexes, capture_naming, store)

    assert _restriction_issues(accepted.warnings) == ()


def test_a_combo_restricted_away_from_the_reported_unit_is_warned_about(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The root is an ancestor of the restricted district rather than beneath it, which DHIS2 refuses."""
    store = _restricted_store(capture_store, DISTRICT_LOCATION)

    accepted = _accept(attribute_combo_response, capture_indexes, capture_naming, store)

    issues = _restriction_issues(accepted.warnings)

    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].diagnostics is not None
    assert f"Location/{ROOT_LOCATION}" in issues[0].diagnostics
    assert f"List/{RESTRICTION_LIST_ID}" in issues[0].diagnostics
    assert "E8025" in issues[0].diagnostics


def test_strict_codes_refuses_a_combo_restricted_away_from_the_reported_unit(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """The restriction grades on the dial an organisation unit outside the assignment grades on."""
    store = _restricted_store(capture_store, DISTRICT_LOCATION)

    with pytest.raises(CaptureRejection) as raised:
        validate_response(json.dumps(attribute_combo_response).encode(), capture_indexes, capture_naming, store, True)

    assert raised.value.http_status == 422
    assert [issue.severity for issue in _restriction_issues(raised.value.issues)] == ["error"]


def test_a_concept_carrying_no_restriction_is_captured_anywhere(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """Absence means the combo is usable wherever the form is, which is what an unrestricted option states."""
    store = _restricted_store(capture_store, DISTRICT_LOCATION, concept_codes=("BqblOcSwGey",))

    accepted = _accept(attribute_combo_response, capture_indexes, capture_naming, store)

    assert _restriction_issues(accepted.warnings) == ()


def test_a_restriction_list_the_facade_does_not_serve_narrows_nothing(
    attribute_combo_response: dict[str, Any],
    capture_indexes: CaptureIndexCache,
    capture_naming: CaptureNaming,
    capture_store: ResourceStore,
) -> None:
    """An artifact this project did not publish states nothing, the way an unresolvable assignment does not."""
    entries = tuple(
        entry.model_copy(update={"body": _restricted_code_system(entry.body, FILED_CONCEPT)})
        if entry.canonical_url == ATTRIBUTE_COMBO_CODE_SYSTEM
        else entry
        for entry in capture_store.entries
    )

    accepted = _accept(attribute_combo_response, capture_indexes, capture_naming, ResourceStore(entries=entries))

    assert _restriction_issues(accepted.warnings) == ()


async def test_generate_draws_a_combo_usable_at_the_unit_it_drew(
    capture_project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
) -> None:
    """Every combo is restricted to one district, so every seed has to report from it and no other unit."""
    project = _restricted_project(capture_project, write_resource, DISTRICT_LOCATION)

    async with _serving(project) as client:
        drawn = {
            (await _generate(client, ATTRIBUTE_COMBO_ID, seed=seed)).json()["subject"]["reference"]
            for seed in VARIANCE_SEEDS
        }

    assert drawn == {f"Location/{DISTRICT_LOCATION}"}


async def test_a_form_whose_combos_are_usable_nowhere_is_not_drafted(
    capture_project: FhirProject,
    write_resource: Callable[[Path, dict[str, Any]], None],
) -> None:
    """One rule, both halves: a combo usable at no admitted unit is one the facade would refuse on receipt."""
    project = _restricted_project(capture_project, write_resource)

    async with _serving(project) as client:
        refused = await _generate(client, ATTRIBUTE_COMBO_ID, seed=3)

    outcome = refused.json()

    assert refused.status_code == 422
    assert outcome["resourceType"] == "OperationOutcome"
    assert "E8025" in outcome["issue"][0]["diagnostics"]


#: The registry package a guide in registry mode names its organisation units under.
REGISTRY_CANONICAL = "http://example.org/fhir/registry"

_REGISTRY_TABLE = f"""
[generate.organisation_units.registry]
id = "dhis2.fhir.registry"
canonical = "{REGISTRY_CANONICAL}"
version = "0.1.0"
path = "."
"""


def _registry_mode(project: FhirProject) -> FhirProject:
    """The golden project as a guide whose organisation units a separate registry package publishes."""
    config_path = project.config_path
    config_path.write_text(config_path.read_text(encoding="utf-8") + _REGISTRY_TABLE, encoding="utf-8")
    return FhirProject(config=load_fhir_config(config_path), config_path=config_path)


async def test_a_guide_publishing_its_own_registry_generates_a_relative_location_reference(
    capture_project: FhirProject,
) -> None:
    """`Location/<id>` is what such a guide's own documents name a unit by, so it is what a draft shows."""
    async with _serving(capture_project) as client:
        generated = (await _generate(client, ATTRIBUTE_COMBO_ID, seed=5)).json()

    reference = generated["subject"]["reference"]

    assert reference.startswith("Location/")
    assert "://" not in reference


async def test_a_registry_mode_guide_generates_an_absolute_location_reference(
    capture_project: FhirProject,
) -> None:
    """A relative reference does not resolve across a package dependency, so a draft names the authority too.

    It is the rule the guide's own examples are written under. Both spellings post - the facade reads
    the id out of either - so the only thing deciding which one a draft carries is which one a client
    copying that draft should learn.
    """
    project = _registry_mode(capture_project)

    async with _serving(project) as client:
        generated = (await _generate(client, ATTRIBUTE_COMBO_ID, seed=5)).json()
        posted = await client.post(
            "/QuestionnaireResponse",
            content=json.dumps(generated).encode(),
            headers={"Content-Type": "application/fhir+json"},
        )

    reference = generated["subject"]["reference"]

    assert reference.startswith(f"{REGISTRY_CANONICAL}/Location/")
    assert posted.status_code == 201
