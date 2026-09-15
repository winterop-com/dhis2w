"""The access log: one line per interaction, the line a starting server writes, and the configuration.

The starting line and the CapabilityStatement two lines below it state the same two counts, and the
tests here hold them to that: the store holds types this server answers no interaction for, so
"across N types" and "N resource types declared" are different numbers and each says which it is.
"""

from __future__ import annotations

import json
import logging
import re
import sys

import httpx2
import pytest
from dhis2w_fhir.config import FhirProject
from dhis2w_fhir_serve.app import create_app
from dhis2w_fhir_serve.log import LOGGER_NAME, configure_logging
from dhis2w_fhir_serve.routes.context import SERVE_CONTEXT_ATTRIBUTE
from dhis2w_fhir_serve.runtime import ServeContext
from dhis2w_fhir_serve.settings import ServeSettings

#: What the starting line states, as the two counts a reader compares against `/metadata`.
STARTING_LINE = re.compile(
    r"(?P<resources>\d+) resources across (?P<held>\d+) types in the store, "
    r"(?P<declared>\d+) resource types declared at /metadata"
)

#: Two resource types the store holds and the FHIR surface answers no interaction for - a project is
#: free to write a StructureMap or a Measure into its own tree, and neither is ever read back here.
#: Two of them, so the store's type count and the statement's differ by more than the
#: QuestionnaireResponse entry the statement declares and the store holds none of.
UNSERVED_RESOURCES = (
    {
        "resourceType": "Measure",
        "id": "d2-coverage-measure",
        "url": "http://example.org/fhir/Measure/d2-coverage-measure",
        "status": "draft",
    },
    {
        "resourceType": "StructureMap",
        "id": "d2-aggregate-map",
        "url": "http://example.org/fhir/StructureMap/d2-aggregate-map",
        "status": "active",
        "group": [],
    },
)


def _write_unserved_resources(project: FhirProject) -> None:
    """Put the two unserved resources into the project's compiled tree, as a build would."""
    compiled = project.ig_directory / "fsh-generated" / "resources"
    for resource in UNSERVED_RESOURCES:
        path = compiled / f"{resource['resourceType']}-{resource['id']}.json"
        path.write_text(json.dumps(resource), encoding="utf-8")


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER_NAME]


async def test_a_served_request_logs_one_line(client: httpx2.AsyncClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.get("/Questionnaire?_id=d2-pr-anc-visit-q")

    lines = [line for line in _messages(caplog) if line.startswith("GET /Questionnaire")]
    assert len(lines) == 1
    assert lines[0].startswith("GET /Questionnaire?_id=d2-pr-anc-visit-q -> 200 ")
    assert lines[0].endswith("ms")


async def test_a_refused_request_logs_its_status(client: httpx2.AsyncClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await client.get("/Patient/anything")

    assert any(line.startswith("GET /Patient/anything -> 404 ") for line in _messages(caplog))


async def test_the_starting_line_counts_what_it_says_it_counts(
    compiled_project: FhirProject, caplog: pytest.LogCaptureFixture
) -> None:
    """The store's types and the statement's are two counts of two things, and the line names each.

    The store holds a Measure and a StructureMap here, which no interaction of this server answers,
    so the two numbers differ - which is the case that makes a line saying only the first read as a
    contradiction of a `/metadata` saying only the second.
    """
    _write_unserved_resources(compiled_project)
    app = create_app(ServeSettings(project_dir=compiled_project.project_root))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        async with app.router.lifespan_context(app):
            context: ServeContext = getattr(app.state, SERVE_CONTEXT_ATTRIBUTE)
            summary = context.store.summary()
            declared = context.capability_body["rest"][0]["resource"]

    stated = next(STARTING_LINE.search(line) for line in _messages(caplog) if STARTING_LINE.search(line))
    assert stated is not None
    assert int(stated["resources"]) == summary.total
    assert int(stated["held"]) == len(summary.counts_by_type)
    assert int(stated["declared"]) == len(declared)
    assert int(stated["held"]) != int(stated["declared"])


async def test_the_statement_states_the_same_two_counts_the_starting_line_does(
    compiled_project: FhirProject, caplog: pytest.LogCaptureFixture
) -> None:
    """Both lines carry both numbers, so neither can be read as the other's contradiction."""
    _write_unserved_resources(compiled_project)
    app = create_app(ServeSettings(project_dir=compiled_project.project_root))

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        async with app.router.lifespan_context(app):
            context: ServeContext = getattr(app.state, SERVE_CONTEXT_ATTRIBUTE)
            summary = context.store.summary()
            description = context.capability_body["description"]
            declared = len(context.capability_body["rest"][0]["resource"])

    assert f"{summary.total} resources across {len(summary.counts_by_type)} types in the store" in description
    assert f"served under the {declared} resource types this statement declares" in description
    stated = next(STARTING_LINE.search(line) for line in _messages(caplog) if STARTING_LINE.search(line))
    assert stated is not None
    assert int(stated["held"]) == len(summary.counts_by_type)
    assert int(stated["declared"]) == declared


def test_configure_logging_sends_this_package_to_stderr() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    handlers, level, propagate = logger.handlers, logger.level, logger.propagate
    try:
        configure_logging()

        assert len(logger.handlers) == 1
        handler = logger.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr
        assert logger.level == logging.INFO
        assert logger.propagate is False
    finally:
        logger.handlers, logger.level, logger.propagate = handlers, level, propagate
