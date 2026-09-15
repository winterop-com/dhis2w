"""`GET|POST /Questionnaire/{id}/$generate` - the instance-level operation that fills a served form.

The operation answers one served Questionnaire with a synthetic QuestionnaireResponse: every question
answered with a value its own type, bounds, and terminology binding admit, wrapped in the context its
form kind's response profile requires. What makes it worth serving is that the answer is immediately
postable - `$generate` output sent to this server's own `POST /QuestionnaireResponse` answers 201,
which is the round trip a capture UI's fill-with-test-data button and an API-driven stress corpus both
stand on. `tests/test_generate_endpoint.py` holds that invariant per form kind.

The spool is read as part of answering: a generated stage response answers against the tracked entity
and the enrollment a spooled registration of the same program minted, so the operation's output is a
function of the project's receipts as well as its forms - see `dhis2w_fhir_serve.synthesize`.

Three inputs steer the draw. `seed` makes it reproducible; `subject` pins the organisation unit the
response reports from; `attributeOptionCombo` pins what it is filed under. The two pins are one rule
in two places: a capture client refilling a form somebody has already made a choice on names the
choice, and the whole context comes back drawn around it rather than around one of the server's own
choosing. What is named is never swapped - a pin the instance does not accept at the other half of
the key is refused with the reason - and what is not named is drawn to agree with what is, so the
pair a client gets back is one the instance accepts together.

This is a **custom** operation, deliberately not SDC's `$populate`. `$populate` means fill this form
from real context about a real subject; `$generate` invents its data, and a client that knows what
`$populate` means would be misled by seeing it here. The IG publishes the OperationDefinition, and
`/metadata` declares it on the Questionnaire resource entry beside the read interactions.

The path is fixed, so this router mounts ahead of the read catch-alls: `/{resource_type}/{resource_id}`
matches `/Questionnaire/BfMAe6Itzgt/$generate` just as happily and would answer it as a read.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from dhis2w_fhir.conversion.values import location_id_of
from dhis2w_fhir.foundation import (
    GENERATE_ATTRIBUTE_OPTION_COMBO_PARAMETER,
    GENERATE_SEED_PARAMETER,
    GENERATE_SUBJECT_PARAMETER,
)
from dhis2w_fhir.names import is_valid_fhir_id
from dhis2w_fhir.r4 import Parameters, ParametersParameter, Questionnaire
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import Response

from dhis2w_fhir_serve.capture.index import QUESTIONNAIRE_RESOURCE_TYPE, UnreadableQuestionnaireError
from dhis2w_fhir_serve.errors import FHIR_JSON_MEDIA_TYPE, BadOperationError, NotFoundError, ServeError
from dhis2w_fhir_serve.routes.capture import capture_state
from dhis2w_fhir_serve.routes.context import serve_context
from dhis2w_fhir_serve.synthesize import (
    MAXIMUM_SEED,
    UngeneratableCaptureError,
    draw_seed,
    generate_response,
)

#: The path the operation is served at; `capability.py` declares it by the name R4 gives it.
GENERATE_PATH = f"/{QUESTIONNAIRE_RESOURCE_TYPE}/{{resource_id}}/$generate"

router = APIRouter()


class UngeneratableFormError(ServeError):
    """The Questionnaire is served, but it is not one this server can generate a response to."""

    status_code = 422
    issue_code = "not-supported"

    def __init__(self, resource_id: str, diagnostics: str) -> None:
        super().__init__(f"`Questionnaire/{resource_id}` cannot be generated against: {diagnostics}")
        self.resource_id = resource_id


class GenerateInputs(BaseModel):
    """The three inputs one `$generate` call steers its draw with, read off the query or a Parameters body."""

    model_config = ConfigDict(frozen=True)

    seed: int | None = None
    subject_location_id: str | None = None
    attribute_option_combo_code: str | None = None


@router.get(GENERATE_PATH)
async def generate_from_questionnaire(request: Request, resource_id: str) -> Response:
    """Answer one served form with a synthetic response, drawn as the query's own inputs steer it."""
    return _generated(request, resource_id, read_inputs(request.query_params))


@router.post(GENERATE_PATH)
async def post_generate_from_questionnaire(request: Request, resource_id: str) -> Response:
    """The POST spelling of the same operation, taking its inputs from a Parameters body or the query."""
    body = await request.body()
    queried = read_inputs(request.query_params)
    carried = read_body_inputs(body)
    return _generated(
        request,
        resource_id,
        GenerateInputs(
            seed=carried.seed if carried.seed is not None else queried.seed,
            subject_location_id=(
                carried.subject_location_id if carried.subject_location_id is not None else queried.subject_location_id
            ),
            attribute_option_combo_code=(
                carried.attribute_option_combo_code
                if carried.attribute_option_combo_code is not None
                else queried.attribute_option_combo_code
            ),
        ),
    )


def read_inputs(params: QueryParams) -> GenerateInputs:
    """Read every input the operation declares off the query string."""
    return GenerateInputs(
        seed=read_seed(params),
        subject_location_id=_checked_subject(params.get(GENERATE_SUBJECT_PARAMETER)),
        attribute_option_combo_code=_checked_attribute_option_combo(
            params.get(GENERATE_ATTRIBUTE_OPTION_COMBO_PARAMETER)
        ),
    )


def read_body_inputs(raw_body: bytes) -> GenerateInputs:
    """Read every input the operation declares off a POSTed Parameters body, which R4 allows.

    An empty body is how a client says "any draw", and is the shape a bare `POST .../$generate`
    sends. A body that is not a Parameters resource is refused rather than ignored: a client that
    meant to name an input and misspelled the resource would otherwise be answered with a different
    response than it asked for, silently.
    """
    seed: int | None = None
    subject: str | None = None
    combo: str | None = None
    for parameter in _body_parameters(raw_body):
        if parameter.name == GENERATE_SEED_PARAMETER:
            seed = _body_seed(parameter)
        elif parameter.name == GENERATE_SUBJECT_PARAMETER:
            subject = _checked_subject(parameter.valueString)
        elif parameter.name == GENERATE_ATTRIBUTE_OPTION_COMBO_PARAMETER:
            combo = _checked_attribute_option_combo(parameter.valueString)
    return GenerateInputs(seed=seed, subject_location_id=subject, attribute_option_combo_code=combo)


def _checked_subject(raw: str | None) -> str | None:
    """One organisation unit as the operation declares it: a `Location/<id>` reference, or its bare id.

    A client that holds the reference sends it whole and one holding only the id sends that, because
    both spell the same organisation unit and refusing either would be this server insisting on a
    spelling the registry itself does not care about.

    THE ID IS WHATEVER THE SERVED LOCATION CARRIES. A guide naming its organisation units by their
    DHIS2 code publishes `Location/OU-226264`, and a server that demanded a DHIS2 UID here would
    refuse every organisation unit such a guide has - while the capture UI beside it sends exactly
    the ids the guide published. So the shape R4 gives an id is the whole of the spelling rule, and
    which organisation units exist is the store's to answer: a `Location` this server serves none of
    is refused where the draw is made, by name and with the count of the ones the form does admit.
    """
    if raw is None or raw == "":
        return None
    location_id = location_id_of(raw) if "/" in raw else raw
    if location_id is None or not is_valid_fhir_id(location_id):
        raise BadOperationError(
            f"`{GENERATE_SUBJECT_PARAMETER}` takes an organisation unit as `Location/<id>`, not `{raw}`"
        )
    return location_id


def _checked_attribute_option_combo(raw: str | None) -> str | None:
    """One attribute option combo as the operation declares it: a concept code, or `<system>|<code>`.

    The token is checked for shape here and resolved against the form's own vocabulary where the
    draw is made, because which combos exist is a fact about the form rather than about the request.
    """
    if raw is None or raw == "":
        return None
    if raw.count("|") > 1 or raw.endswith("|"):
        raise BadOperationError(
            f"`{GENERATE_ATTRIBUTE_OPTION_COMBO_PARAMETER}` takes an attribute option combo as a concept code "
            f"or as `<system>|<code>`, not `{raw}`"
        )
    return raw


def read_seed(params: QueryParams) -> int | None:
    """Read the `seed` query parameter, refusing anything the operation's `integer` input cannot carry."""
    raw = params.get(GENERATE_SEED_PARAMETER)
    if raw is None or raw == "":
        return None
    return _checked_seed(raw)


def _body_seed(parameter: ParametersParameter) -> int:
    """One seed as a POSTed Parameters body carries it, on `valueInteger` or as a string beside it."""
    if parameter.valueInteger is not None:
        return _checked_seed(str(parameter.valueInteger))
    if parameter.valueString is not None:
        return _checked_seed(parameter.valueString)
    raise BadOperationError(f"the `{GENERATE_SEED_PARAMETER}` parameter carries no `valueInteger`")


def _body_parameters(raw_body: bytes) -> list[ParametersParameter]:
    """Every parameter a POSTed body names, an empty body naming none."""
    if not raw_body.strip():
        return []
    try:
        payload: Any = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise BadOperationError(f"the request body is not valid JSON ({error})") from error
    try:
        parameters = Parameters.model_validate(payload)
    except ValidationError as error:
        raise BadOperationError(f"the request body is not a Parameters resource ({error})") from error
    return parameters.parameter or []


def _checked_seed(raw: str) -> int:
    """One seed as the operation declares it: a non-negative R4 integer."""
    try:
        seed = int(raw)
    except ValueError as error:
        raise BadOperationError(f"`{GENERATE_SEED_PARAMETER}` takes a whole number, not `{raw}`") from error
    if seed < 0 or seed > MAXIMUM_SEED:
        raise BadOperationError(f"`{GENERATE_SEED_PARAMETER}` takes a value between 0 and {MAXIMUM_SEED}")
    return seed


def _generated(request: Request, resource_id: str, inputs: GenerateInputs) -> Response:
    """Resolve the named form, generate one response to it, and serialise it as the operation's output."""
    context = serve_context(request)
    state = capture_state(request)
    entry = context.store.by_type_and_id(QUESTIONNAIRE_RESOURCE_TYPE, resource_id)
    if entry is None or entry.canonical_url is None:
        raise NotFoundError(QUESTIONNAIRE_RESOURCE_TYPE, resource_id)
    try:
        index = state.indexes.resolve(entry.canonical_url, state.naming, context.store)
        questionnaire = Questionnaire.model_validate(entry.body)
        response = generate_response(
            questionnaire,
            index,
            state.naming,
            context.store,
            seed=inputs.seed if inputs.seed is not None else draw_seed(),
            today=datetime.date.today(),
            spool=context.spool,
            subject_location_id=inputs.subject_location_id,
            attribute_option_combo_code=inputs.attribute_option_combo_code,
        )
    except (UnreadableQuestionnaireError, UngeneratableCaptureError, ValidationError) as error:
        raise UngeneratableFormError(resource_id, _diagnostics(error)) from error
    return Response(
        content=response.model_dump_json(exclude_none=True, by_alias=True),
        media_type=FHIR_JSON_MEDIA_TYPE,
    )


def _diagnostics(error: UnreadableQuestionnaireError | UngeneratableCaptureError | ValidationError) -> str:
    """Say why a served Questionnaire could not be generated against, in the terms it failed on."""
    if isinstance(error, UnreadableQuestionnaireError | UngeneratableCaptureError):
        return error.diagnostics
    return str(error)
