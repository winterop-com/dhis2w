"""Serving a package: a project that publishes organisation units for guides to depend on, and no form.

A package is not a guide with an empty form catalogue - it holds no Questionnaire and never will -
so every surface that would otherwise offer a capture says what the project is instead: the
CapabilityStatement declares no QuestionnaireResponse and no `$generate`, the service base says it
while refusing the read, and a submission is refused with the same sentence rather than with a
complaint about the document's form type.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from dhis2w_fhir.config import FhirProject, load_fhir_config
from dhis2w_fhir_serve.app import create_app
from dhis2w_fhir_serve.capability import QUESTIONNAIRE_RESPONSE_RESOURCE_TYPE
from dhis2w_fhir_serve.errors import package_statement
from dhis2w_fhir_serve.settings import ServeSettings
from fastapi import FastAPI

BASE_URL = "http://package.test"

CANONICAL = "http://example.org/fhir/registry"

PACKAGE_FHIR_TOML = f"""
[ig]
id = "dhis2.fhir.example.registry"
canonical = "{CANONICAL}"
name = "Dhis2FhirExampleRegistry"
title = "DHIS2 FHIR Example Registry"
publisher = "Example Organisation"
kind = "package"
publishes = "organisation-units"
"""

#: The sentence every surface of a package says, composed the one way the package composes it.
PACKAGE_SENTENCE = package_statement("organisation-units")

LOCATION = {
    "resourceType": "Location",
    "id": "ImspTQPwCqd",
    "name": "Sierra Leone",
    "identifier": [{"system": "http://dhis2.org/fhir/id/org-unit", "value": "ImspTQPwCqd"}],
}

ORGANIZATION = {
    "resourceType": "Organization",
    "id": "ImspTQPwCqd",
    "name": "Sierra Leone",
    "identifier": [{"system": "http://dhis2.org/fhir/id/org-unit", "value": "ImspTQPwCqd"}],
}


def _write(path: Path, resource: dict[str, Any]) -> None:
    """Write one resource file into a project tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(resource, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def package_project(tmp_path: Path) -> FhirProject:
    """The organisation-unit package, compiled: two places and nothing else."""
    config_path = tmp_path / "fhir.toml"
    config_path.write_text(PACKAGE_FHIR_TOML, encoding="utf-8")
    _write(tmp_path / "ig" / "fsh-generated" / "resources" / "Location-ImspTQPwCqd.json", LOCATION)
    _write(tmp_path / "ig" / "input" / "resources" / "registry" / "Organization-ImspTQPwCqd.json", ORGANIZATION)
    return FhirProject(config=load_fhir_config(config_path), config_path=config_path.resolve())


@pytest.fixture
def package_app(package_project: FhirProject) -> FastAPI:
    """The facade over the package, started the way `d2w fhir serve` starts it."""
    return create_app(ServeSettings.resolve(package_project).settings)


@pytest.fixture
async def package_client(package_app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """An in-process client over the package facade, with the lifespan run around the test."""
    async with package_app.router.lifespan_context(package_app):
        transport = httpx2.ASGITransport(app=package_app)
        async with httpx2.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            yield http


async def _statement(client: httpx2.AsyncClient) -> dict[str, Any]:
    """The CapabilityStatement this process answers `/metadata` with."""
    response = await client.get("/metadata")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def test_the_statement_declares_no_questionnaire_response(package_client: httpx2.AsyncClient) -> None:
    """A package receives nothing, so the entry that says "post your submissions here" is not declared."""
    statement = await _statement(package_client)

    declared = [resource["type"] for resource in statement["rest"][0]["resource"]]
    assert QUESTIONNAIRE_RESPONSE_RESOURCE_TYPE not in declared
    assert "Location" in declared


async def test_the_statement_declares_no_generate_operation(package_client: httpx2.AsyncClient) -> None:
    """`$generate` fills a published form, and a package publishes none to fill."""
    statement = await _statement(package_client)

    operations = [
        operation["name"]
        for resource in statement["rest"][0]["resource"]
        for operation in resource.get("operation", [])
    ]
    assert "generate" not in operations


async def test_the_statement_says_what_the_package_publishes(package_client: httpx2.AsyncClient) -> None:
    """A reader of the conformance document learns the project's shape, not that it is a capture facade."""
    statement = await _statement(package_client)

    assert PACKAGE_SENTENCE in statement["description"]
    assert "served as a FHIR capture facade" not in statement["description"]
    assert "organisation units" in statement["implementation"]["description"]
    assert "receives no QuestionnaireResponse" in statement["rest"][0]["documentation"]


async def test_the_service_base_says_what_the_package_publishes(package_client: httpx2.AsyncClient) -> None:
    """The base URL is where a browser lands first, and "not an endpoint" alone sends a reader hunting."""
    response = await package_client.get("/")

    assert response.status_code == 404
    assert PACKAGE_SENTENCE in response.json()["issue"][0]["diagnostics"]


async def test_a_submission_is_refused_with_the_package_sentence(package_client: httpx2.AsyncClient) -> None:
    """The refusal names the project rather than the document: no body a client could send would do."""
    response = await package_client.post(
        f"/{QUESTIONNAIRE_RESPONSE_RESOURCE_TYPE}",
        content=json.dumps({"resourceType": "QuestionnaireResponse", "status": "completed"}),
        headers={"Content-Type": "application/fhir+json"},
    )

    assert response.status_code == 405
    diagnostics = response.json()["issue"][0]["diagnostics"]
    assert PACKAGE_SENTENCE in diagnostics
    assert "form type" not in diagnostics


def test_the_sentence_spells_the_organisation_units_out() -> None:
    """The token `organisation-units` is the machine spelling; a sentence a person reads says the words."""
    assert "it publishes organisation units for guides to depend on, and no form" in PACKAGE_SENTENCE


@pytest.mark.parametrize("resource_type", ["Questionnaire", "QuestionnaireResponse", "Measure", "Bundle"])
async def test_a_type_the_package_declares_no_interaction_for_is_refused(
    package_client: httpx2.AsyncClient, resource_type: str
) -> None:
    """The statement is the route table: an empty searchset would say the package published none of these."""
    statement = await _statement(package_client)
    assert resource_type not in [resource["type"] for resource in statement["rest"][0]["resource"]]

    response = await package_client.get(f"/{resource_type}")

    assert response.status_code == 404
    assert response.json()["resourceType"] == "OperationOutcome"
    assert "does not serve the resource type" in response.json()["issue"][0]["diagnostics"]


async def test_every_type_the_package_declares_answers_a_search(package_client: httpx2.AsyncClient) -> None:
    """One set, one meaning: what `/metadata` declares is what the read catch-all answers, exactly."""
    statement = await _statement(package_client)

    declared = {resource["type"] for resource in statement["rest"][0]["resource"]}

    for resource_type in sorted(declared):
        response = await package_client.get(f"/{resource_type}")
        assert response.status_code == 200, resource_type
