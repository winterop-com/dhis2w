"""`GET /{type}/{id}`: what the facade serves, what it refuses, and what it holds back."""

from __future__ import annotations

import json

import httpx2
from dhis2w_fhir.config import FhirProject
from dhis2w_fhir_serve.spool import StoredResponseEnvelope
from fixture_project import ORG_UNIT_IDENTIFIER_SYSTEM, ORG_UNITS

FHIR_JSON = "application/fhir+json"

#: The worked example the fixture guide compiles beside its registry profiles, and publishes as nothing.
EXEMPLAR_LOCATION_ID = "d2-location-example"


async def test_read_returns_the_compiled_file_verbatim(
    client: httpx2.AsyncClient, compiled_project: FhirProject
) -> None:
    compiled = compiled_project.ig_directory / "fsh-generated" / "resources" / "Questionnaire-d2-pr-anc-visit-q.json"

    response = await client.get("/Questionnaire/d2-pr-anc-visit-q")

    assert response.status_code == 200
    assert response.json() == json.loads(compiled.read_text(encoding="utf-8"))


async def test_read_answers_as_fhir_json(client: httpx2.AsyncClient) -> None:
    response = await client.get("/Questionnaire/d2-pr-anc-visit-q")

    assert response.headers["content-type"] == FHIR_JSON


async def test_read_serves_the_predefined_tree_too(client: httpx2.AsyncClient) -> None:
    response = await client.get("/Organization/X")

    assert response.status_code == 200
    assert response.json()["name"] == "Sierra Leone"


async def test_read_of_an_unknown_id_is_not_found(client: httpx2.AsyncClient) -> None:
    response = await client.get("/Questionnaire/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == FHIR_JSON
    body = response.json()
    assert body["resourceType"] == "OperationOutcome"
    assert body["issue"][0]["code"] == "not-found"
    assert "nope" in body["issue"][0]["diagnostics"]


async def test_read_of_an_unserved_type_is_not_supported(client: httpx2.AsyncClient) -> None:
    response = await client.get("/Patient/anything")

    assert response.status_code == 404
    assert response.json()["issue"][0]["code"] == "not-supported"


async def test_a_profile_the_guide_publishes_is_read_like_every_other_resource(
    client: httpx2.AsyncClient,
) -> None:
    """A served project hosts its own guide, so a profile it published is answered at its own address."""
    response = await client.get("/StructureDefinition/d2-aggregate-response")

    assert response.status_code == 200
    assert response.headers["content-type"] == FHIR_JSON
    body = response.json()
    assert body["resourceType"] == "StructureDefinition"
    assert body["url"] == "http://example.org/fhir/StructureDefinition/d2-aggregate-response"
    assert body["type"] == "QuestionnaireResponse"


async def test_reading_a_receipt_returns_the_submission_as_received(
    client: httpx2.AsyncClient, stored_responses: tuple[StoredResponseEnvelope, ...]
) -> None:
    envelope = stored_responses[1]

    response = await client.get(f"/QuestionnaireResponse/{envelope.response_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == FHIR_JSON
    assert response.json() == envelope.response


async def test_reading_an_unknown_receipt_is_not_found(client: httpx2.AsyncClient) -> None:
    response = await client.get("/QuestionnaireResponse/receipt-missing")

    assert response.status_code == 404
    assert response.json()["issue"][0]["code"] == "not-found"


async def test_the_organisation_units_answered_are_the_ones_the_guide_published(
    capture_client: httpx2.AsyncClient,
) -> None:
    """The count a consumer reads back is the count `d2w fhir generate` wrote, exemplar or no exemplar."""
    counted = await capture_client.get("/Location?_count=0")
    listed = await capture_client.get("/Location?_count=50")

    assert counted.json()["total"] == len(ORG_UNITS)
    assert listed.json()["total"] == len(ORG_UNITS)
    served = {entry["resource"]["id"] for entry in listed.json()["entry"]}
    assert served == {unit.uid for unit in ORG_UNITS}
    assert EXEMPLAR_LOCATION_ID not in served


async def test_the_worked_example_is_still_read_at_the_address_the_guide_links_to(
    capture_client: httpx2.AsyncClient,
) -> None:
    """A published page links to its own example by id, and this server is where that link resolves."""
    response = await capture_client.get(f"/Location/{EXEMPLAR_LOCATION_ID}")

    assert response.status_code == 200
    assert response.headers["content-type"] == FHIR_JSON
    assert response.json()["id"] == EXEMPLAR_LOCATION_ID


async def test_an_organisation_unit_search_by_identifier_answers_the_published_unit(
    capture_client: httpx2.AsyncClient,
) -> None:
    """The exemplar carries the root unit's own identifier, and answers no search for it."""
    root = ORG_UNITS[0]

    response = await capture_client.get(f"/Location?identifier={ORG_UNIT_IDENTIFIER_SYSTEM}|{root.uid}")

    assert response.json()["total"] == 1
    assert [entry["resource"]["id"] for entry in response.json()["entry"]] == [root.uid]
