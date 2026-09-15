"""Unit tests for the IG resource store: loading both trees, reads, search semantics, and summary."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from dhis2w_fhir.config import FhirProject
from dhis2w_fhir_serve.log import LOGGER_NAME
from dhis2w_fhir_serve.store import (
    CompiledIgMissingError,
    IdentifierToken,
    ResourceStore,
    SearchQuery,
    StoreEntry,
    load_compiled_store,
)

CANONICAL = "http://example.org/fhir"
PROGRAM_SYSTEM = "http://dhis2.org/fhir/id/program"

WriteResource = Callable[[Path, dict[str, Any]], None]


def test_load_merges_both_trees(compiled_project: FhirProject) -> None:
    """The compiled tree and the predefined resource tree land in one store."""
    store = load_compiled_store(compiled_project)

    assert store.types_present() == (
        "CodeSystem",
        "ImplementationGuide",
        "Organization",
        "Questionnaire",
        "StructureDefinition",
    )
    assert len(store.entries) == 5


def test_load_reads_foreign_resource_types(compiled_project: FhirProject) -> None:
    """Types this repo has no model for load byte-faithfully."""
    store = load_compiled_store(compiled_project)

    structure_definition = store.by_type_and_id("StructureDefinition", "d2-aggregate-response")

    assert structure_definition is not None
    assert structure_definition.body["kind"] == "resource"
    assert structure_definition.source == "ig/fsh-generated/resources/StructureDefinition-d2-aggregate-response.json"


def test_load_records_predefined_source_path(compiled_project: FhirProject) -> None:
    """A predefined resource carries its path under the project, not an absolute one."""
    store = load_compiled_store(compiled_project)

    organization = store.by_type_and_id("Organization", "X")

    assert organization is not None
    assert organization.source == "ig/input/resources/registry/Organization-X.json"


def test_missing_compiled_ig_raises(empty_project: FhirProject) -> None:
    """A project that was never compiled points at the generate-then-sushi sequence."""
    with pytest.raises(CompiledIgMissingError) as raised:
        load_compiled_store(empty_project)

    assert str(raised.value) == (
        "no compiled IG at ig/fsh-generated/resources - run `d2w fhir generate`, "
        "then `make sushi` in the project, and serve again."
    )


def test_empty_compiled_directory_raises(empty_project: FhirProject) -> None:
    """An existing but empty compiled directory is the same failure as a missing one."""
    (empty_project.ig_directory / "fsh-generated" / "resources").mkdir(parents=True)

    with pytest.raises(CompiledIgMissingError):
        load_compiled_store(empty_project)


def test_corrupt_json_fails_loudly_naming_the_file(compiled_project: FhirProject) -> None:
    """Unparseable JSON names the file rather than being skipped."""
    corrupt = compiled_project.ig_directory / "fsh-generated" / "resources" / "Questionnaire-broken.json"
    corrupt.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match=r"Questionnaire-broken\.json: not valid JSON"):
        load_compiled_store(compiled_project)


def test_missing_resource_type_fails_loudly_naming_the_file(
    compiled_project: FhirProject, write_resource: WriteResource
) -> None:
    """A JSON object without resourceType names the file."""
    write_resource(
        compiled_project.ig_directory / "fsh-generated" / "resources" / "Nameless.json",
        {"id": "x"},
    )

    with pytest.raises(ValueError, match=r"Nameless\.json: resource has no `resourceType`"):
        load_compiled_store(compiled_project)


def test_missing_id_fails_loudly_naming_the_file(compiled_project: FhirProject, write_resource: WriteResource) -> None:
    """A resource without an id names the file."""
    write_resource(
        compiled_project.ig_directory / "fsh-generated" / "resources" / "Idless.json",
        {"resourceType": "Questionnaire"},
    )

    with pytest.raises(ValueError, match=r"Idless\.json: resource has no `id`"):
        load_compiled_store(compiled_project)


def test_by_type_and_id(compiled_project: FhirProject) -> None:
    """A read resolves by type and id, and misses return None."""
    store = load_compiled_store(compiled_project)

    found = store.by_type_and_id("Questionnaire", "d2-pr-anc-visit-q")

    assert found is not None
    assert found.body["title"] == "ANC Visit"
    assert store.by_type_and_id("Questionnaire", "nope") is None
    assert store.by_type_and_id("Organization", "d2-pr-anc-visit-q") is None


def test_by_canonical(compiled_project: FhirProject) -> None:
    """A canonical url resolves whatever the type, and a resource without a url is unreachable that way."""
    store = load_compiled_store(compiled_project)

    assert store.by_canonical(f"{CANONICAL}/Questionnaire/d2-pr-anc-visit-q") is not None
    assert store.by_canonical(f"{CANONICAL}/StructureDefinition/d2-aggregate-response") is not None
    assert store.by_canonical(f"{CANONICAL}/Organization/X") is None


def test_search_without_parameters_returns_every_resource_of_the_type(compiled_project: FhirProject) -> None:
    """An empty query is a type-wide listing."""
    store = load_compiled_store(compiled_project)

    assert len(store.search("Questionnaire", SearchQuery())) == 1
    assert store.search("Patient", SearchQuery()) == ()


def test_search_by_id_ors_within_the_field(compiled_project: FhirProject, write_resource: WriteResource) -> None:
    """Several ids match either."""
    write_resource(
        compiled_project.ig_directory / "fsh-generated" / "resources" / "Questionnaire-second.json",
        {"resourceType": "Questionnaire", "id": "second", "status": "draft"},
    )
    store = load_compiled_store(compiled_project)

    found = store.search("Questionnaire", SearchQuery(ids=("d2-pr-anc-visit-q", "second")))

    assert {entry.resource_id for entry in found} == {"d2-pr-anc-visit-q", "second"}
    assert store.search("Questionnaire", SearchQuery(ids=("second",)))[0].resource_id == "second"


def test_search_by_url(compiled_project: FhirProject) -> None:
    """A url search matches the canonical, and a resource without one never matches."""
    store = load_compiled_store(compiled_project)

    found = store.search("Questionnaire", SearchQuery(urls=(f"{CANONICAL}/Questionnaire/d2-pr-anc-visit-q",)))

    assert len(found) == 1
    assert store.search("Organization", SearchQuery(urls=(f"{CANONICAL}/Organization/X",))) == ()


def test_search_by_identifier_with_system(compiled_project: FhirProject) -> None:
    """A system-qualified token matches only that system."""
    store = load_compiled_store(compiled_project)

    qualified = SearchQuery(identifiers=(IdentifierToken(system=PROGRAM_SYSTEM, value="ZzYYXq4fJie"),))
    wrong_system = SearchQuery(identifiers=(IdentifierToken(system="http://elsewhere", value="ZzYYXq4fJie"),))

    assert len(store.search("Questionnaire", qualified)) == 1
    assert store.search("Questionnaire", wrong_system) == ()


def test_search_by_identifier_without_system_matches_any_system(compiled_project: FhirProject) -> None:
    """A bare token matches the value in whichever system carries it."""
    store = load_compiled_store(compiled_project)

    bare = SearchQuery(identifiers=(IdentifierToken(value="ZzYYXq4fJie"),))
    bare_on_systemless_resource = SearchQuery(identifiers=(IdentifierToken(value="bare-token-no-system"),))

    assert len(store.search("Questionnaire", bare)) == 1
    assert len(store.search("CodeSystem", bare_on_systemless_resource)) == 1


def test_search_ors_within_the_identifier_field(compiled_project: FhirProject) -> None:
    """Several identifier tokens match either."""
    store = load_compiled_store(compiled_project)

    query = SearchQuery(
        identifiers=(
            IdentifierToken(value="not-in-the-ig"),
            IdentifierToken(system=PROGRAM_SYSTEM, value="ZzYYXq4fJie"),
        )
    )

    assert len(store.search("Questionnaire", query)) == 1


def test_search_ands_across_fields(compiled_project: FhirProject) -> None:
    """Fields combine with AND, so one miss drops the resource."""
    store = load_compiled_store(compiled_project)

    both_match = SearchQuery(
        ids=("d2-pr-anc-visit-q",),
        identifiers=(IdentifierToken(system=PROGRAM_SYSTEM, value="ZzYYXq4fJie"),),
    )
    one_misses = SearchQuery(
        ids=("d2-pr-anc-visit-q",),
        identifiers=(IdentifierToken(value="not-in-the-ig"),),
    )

    assert len(store.search("Questionnaire", both_match)) == 1
    assert store.search("Questionnaire", one_misses) == ()


def test_summary_counts_by_type(compiled_project: FhirProject) -> None:
    """The summary reports one count per type, and totals them."""
    store = load_compiled_store(compiled_project)

    summary = store.summary()

    assert summary.counts_by_type == {
        "CodeSystem": 1,
        "ImplementationGuide": 1,
        "Organization": 1,
        "Questionnaire": 1,
        "StructureDefinition": 1,
    }
    assert summary.total == 5


def test_summary_of_an_empty_store() -> None:
    """A store with no entries summarises to nothing rather than failing."""
    store = ResourceStore()

    assert store.summary().counts_by_type == {}
    assert store.summary().total == 0
    assert store.types_present() == ()


def _concept_map_entry(resource_id: str, body: dict[str, Any]) -> StoreEntry:
    """One stored ConceptMap, as the predefined tree carries it."""
    return StoreEntry(
        resource_type="ConceptMap",
        resource_id=resource_id,
        source=f"ig/input/resources/concept-maps/ConceptMap-{resource_id}.json",
        body=body,
    )


def test_concept_maps_are_parsed_into_models_at_load() -> None:
    """The stored maps come back as R4 models, in load order, so `$translate` reads mappings not documents."""
    store = ResourceStore(
        entries=(
            _concept_map_entry(
                "cm",
                {
                    "resourceType": "ConceptMap",
                    "id": "cm",
                    "url": f"{CANONICAL}/ConceptMap/cm",
                    "group": [
                        {
                            "source": f"{CANONICAL}/CodeSystem/cs",
                            "target": "http://dhis2.org/fhir/id/option",
                            "element": [{"code": "kRRUtYaGett", "target": [{"code": "NB", "equivalence": "equal"}]}],
                        }
                    ],
                },
            ),
        )
    )

    concept_maps = store.concept_maps()

    assert [concept_map.url for concept_map in concept_maps] == [f"{CANONICAL}/ConceptMap/cm"]
    group = (concept_maps[0].group or [])[0]
    assert group.target == "http://dhis2.org/fhir/id/option"
    assert (group.element or [])[0].code == "kRRUtYaGett"


def test_a_concept_map_this_server_cannot_read_is_left_out(caplog: pytest.LogCaptureFixture) -> None:
    """An IG is free to hand-write elements no model here names; that map is skipped and named in the log."""
    store = ResourceStore(
        entries=(
            _concept_map_entry("readable", {"resourceType": "ConceptMap", "id": "readable"}),
            _concept_map_entry("foreign", {"resourceType": "ConceptMap", "id": "foreign", "unmapped": {}}),
        )
    )

    assert [concept_map.id for concept_map in store.concept_maps()] == ["readable"]
    assert "ConceptMap-foreign.json" in caplog.text


def test_a_store_holding_no_concept_map_translates_nothing() -> None:
    """A project that published no ConceptMap has no mappings to answer from."""
    assert ResourceStore().concept_maps() == ()


def test_first_entry_wins_on_duplicate_type_and_id() -> None:
    """When both trees carry the same type and id, the first loaded is the one read back."""
    store = ResourceStore(
        entries=(
            StoreEntry(
                resource_type="Questionnaire",
                resource_id="q",
                source="ig/fsh-generated/resources/Questionnaire-q.json",
                body={"resourceType": "Questionnaire", "id": "q", "title": "compiled"},
            ),
            StoreEntry(
                resource_type="Questionnaire",
                resource_id="q",
                source="ig/input/resources/Questionnaire-q.json",
                body={"resourceType": "Questionnaire", "id": "q", "title": "predefined"},
            ),
        )
    )

    found = store.by_type_and_id("Questionnaire", "q")

    assert found is not None
    assert found.body["title"] == "compiled"


#: The identifier system a generated Location carries its DHIS2 organisation unit UID on, which the
#: worked exemplar carries one of too - so a search by it is where the exemplar would shadow a real
#: unit if it were published.
ORG_UNIT_SYSTEM = "http://dhis2.org/fhir/id/org-unit"

#: The root unit of the fixture registry, and the exemplar compiled beside it.
PUBLISHED_UNIT_ID = "ImspTQPwCqd"
EXEMPLAR_LOCATION_ID = "d2-location-example"


def _location(resource_id: str, unit_uid: str) -> dict[str, Any]:
    """One organisation unit as a Location, carrying its DHIS2 UID as the identifier it is found by."""
    return {
        "resourceType": "Location",
        "id": resource_id,
        "identifier": [{"system": ORG_UNIT_SYSTEM, "value": unit_uid}],
        "status": "active",
        "name": "Sierra Leone",
    }


def _guide_declaring_the_exemplar(*, absolute: bool = False) -> dict[str, Any]:
    """The compiled guide, listing the published unit and calling the exemplar beside it an example."""
    exemplar = f"Location/{EXEMPLAR_LOCATION_ID}"
    return {
        "resourceType": "ImplementationGuide",
        "id": "dhis2.fhir.example",
        "url": f"{CANONICAL}/ImplementationGuide/dhis2.fhir.example",
        "status": "draft",
        "packageId": "dhis2.fhir.example",
        "definition": {
            "resource": [
                {"reference": {"reference": f"Location/{PUBLISHED_UNIT_ID}"}, "exampleBoolean": False},
                {
                    "reference": {"reference": f"{CANONICAL}/{exemplar}" if absolute else exemplar},
                    "exampleCanonical": f"{CANONICAL}/StructureDefinition/d2-location",
                },
            ]
        },
    }


def _project_with_an_exemplar(
    project: FhirProject, write_resource: WriteResource, *, absolute: bool = False
) -> FhirProject:
    """The compiled project with a published organisation unit, the exemplar, and the guide naming both."""
    compiled = project.ig_directory / "fsh-generated" / "resources"
    write_resource(
        compiled / "ImplementationGuide-dhis2.fhir.example.json",
        _guide_declaring_the_exemplar(absolute=absolute),
    )
    write_resource(compiled / f"Location-{EXEMPLAR_LOCATION_ID}.json", _location(EXEMPLAR_LOCATION_ID, "d2-example"))
    registry = project.resources_directory / "registry"
    write_resource(registry / f"Location-{PUBLISHED_UNIT_ID}.json", _location(PUBLISHED_UNIT_ID, PUBLISHED_UNIT_ID))
    return project


def test_an_instance_the_guide_calls_an_example_is_published_by_nothing(
    compiled_project: FhirProject, write_resource: WriteResource
) -> None:
    """One Location is published and one illustrates the profile, and only the first is served."""
    store = load_compiled_store(_project_with_an_exemplar(compiled_project, write_resource))

    assert [entry.resource_id for entry in store.search("Location", SearchQuery())] == [PUBLISHED_UNIT_ID]
    assert store.summary().counts_by_type["Location"] == 1
    assert store.summary().example_count == 1
    assert [entry.resource_id for entry in store.example_entries] == [EXEMPLAR_LOCATION_ID]
    assert store.serves("Location", PUBLISHED_UNIT_ID)
    assert not store.serves("Location", EXEMPLAR_LOCATION_ID)


def test_an_example_is_still_read_at_its_own_address(
    compiled_project: FhirProject, write_resource: WriteResource
) -> None:
    """The guide's own pages link to it by id, so the link resolves even though no search finds it."""
    store = load_compiled_store(_project_with_an_exemplar(compiled_project, write_resource))

    found = store.by_type_and_id("Location", EXEMPLAR_LOCATION_ID)

    assert found is not None
    assert found.body["id"] == EXEMPLAR_LOCATION_ID


def test_an_identifier_search_answers_the_published_unit_and_not_the_example(
    compiled_project: FhirProject, write_resource: WriteResource
) -> None:
    """The search that finds one organisation unit by its DHIS2 UID is untouched by the exemplar."""
    store = load_compiled_store(_project_with_an_exemplar(compiled_project, write_resource))

    query = SearchQuery(identifiers=(IdentifierToken(system=ORG_UNIT_SYSTEM, value=PUBLISHED_UNIT_ID),))

    assert [entry.resource_id for entry in store.search("Location", query)] == [PUBLISHED_UNIT_ID]


def test_an_example_declared_by_an_absolute_reference_is_read_as_the_instance_it_names(
    compiled_project: FhirProject, write_resource: WriteResource
) -> None:
    """A guide naming its own contents under the canonical it publishes at names the same instances."""
    store = load_compiled_store(_project_with_an_exemplar(compiled_project, write_resource, absolute=True))

    assert [entry.resource_id for entry in store.example_entries] == [EXEMPLAR_LOCATION_ID]


def test_a_guide_declaring_no_example_publishes_everything_it_holds(compiled_project: FhirProject) -> None:
    """The guide resource states no contents here, so nothing is held back from what it publishes."""
    store = load_compiled_store(compiled_project)

    assert store.example_entries == ()
    assert store.summary().example_count == 0


def test_a_guide_this_server_cannot_read_costs_its_own_declarations(
    compiled_project: FhirProject, write_resource: WriteResource, caplog: pytest.LogCaptureFixture
) -> None:
    """One malformed guide resource never decides what a whole store publishes - it is named and passed over."""
    project = _project_with_an_exemplar(compiled_project, write_resource)
    compiled = project.ig_directory / "fsh-generated" / "resources"
    write_resource(
        compiled / "ImplementationGuide-dhis2.fhir.example.json",
        {
            "resourceType": "ImplementationGuide",
            "id": "dhis2.fhir.example",
            "definition": {"resource": "not a list of resources"},
        },
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        store = load_compiled_store(project)

    assert store.example_entries == ()
    assert any("states contents this server cannot read" in record.getMessage() for record in caplog.records)
