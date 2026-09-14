"""`GET /metadata` - the conformance endpoint, answered from a body built once at startup.

The statement describes what this process serves, so it is built in the lifespan and served verbatim
from then on. Rebuilding it per request would re-read nothing new: the compiled store is fixed for
the life of the process. It states no spool count for the opposite reason - `d2w fhir forward` moves
receipts while this server runs, so a number frozen at startup is wrong within minutes, and no number
is better than a wrong one. `GET /facade/spool` answers that question against the directory as it now is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from dhis2w_fhir_serve.capability import build_server_capability
from dhis2w_fhir_serve.errors import FHIR_JSON_MEDIA_TYPE
from dhis2w_fhir_serve.routes.context import serve_context

if TYPE_CHECKING:
    from dhis2w_fhir.config import FhirProject

    from dhis2w_fhir_serve.register.surface import RegisterSurface
    from dhis2w_fhir_serve.settings import ServeSettings
    from dhis2w_fhir_serve.store import StoreSummary

router = APIRouter()


class ServedMetadata(BaseModel):
    """The `/metadata` document this process answers with, and the resource types it declares.

    The types ride beside the body because two lines of a starting server state them - the document
    itself and the log line `dhis2w_fhir_serve.app` writes - and a count derived twice is a count
    that can disagree with itself. Reading them back out of the body would mean walking the wire
    document as a dict, which is the one thing the body is not for.
    """

    model_config = ConfigDict(frozen=True)

    body: dict[str, Any]
    """The wire document itself - the same HTTP-boundary escape hatch `StoreEntry.body` documents."""

    declared_resource_types: tuple[str, ...]
    """Every resource type the statement declares an interaction for, in the order it declares them."""


def build_served_metadata(
    project: FhirProject,
    store_summary: StoreSummary,
    settings: ServeSettings,
    register_surface: RegisterSurface,
    server_version: str,
) -> ServedMetadata:
    """Render the server's CapabilityStatement, and name the resource types it declares.

    The body is held pre-rendered so the endpoint serialises nothing per request, and the declared
    types are read off the statement that was just built rather than recomposed from the inputs.
    """
    capability = build_server_capability(
        project=project,
        store_summary=store_summary,
        settings=settings,
        register_surface=register_surface,
        server_version=server_version,
    )
    return ServedMetadata(
        body=capability.model_dump(mode="json", exclude_none=True, by_alias=True),
        # R4 leaves `CapabilityStatementResource.type` optional and every entry this builder writes
        # states one, so an entry without a type is not a type this server declares.
        declared_resource_types=tuple(
            resource.type
            for rest in capability.rest or []
            for resource in rest.resource or []
            if resource.type is not None
        ),
    )


@router.get("/metadata")
async def read_metadata(request: Request) -> Response:
    """Answer with the CapabilityStatement this server started with."""
    return JSONResponse(content=serve_context(request).capability_body, media_type=FHIR_JSON_MEDIA_TYPE)
