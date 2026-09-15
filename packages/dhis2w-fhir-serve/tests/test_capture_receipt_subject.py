"""What the 201 says a receipt holds: the form, the organisation unit, the period, and the combo.

A UUID separates one receipt from another and says nothing about either, so a client that posted a
batch cannot tell from the answers which draft landed where. The information issue on an accepted
capture therefore names the tuple `d2w fhir forward` grades the receipt by and DHIS2 keys the values
it writes by - and names only the parts the submission really carries, since a tracker response
reports for no period and a form on the default category combo is keyed to no attribute option combo.
"""

from __future__ import annotations

from typing import Any

import httpx2
import pytest
from dhis2w_fhir_serve.capture import CaptureSubject, capture_subject_sentence

pytestmark = pytest.mark.usefixtures("capture_client")


async def _diagnostics(client: httpx2.AsyncClient, body: dict[str, Any]) -> str:
    """Post one submission and read the information issue back off the 201."""
    created = await client.post("/QuestionnaireResponse", json=body)
    assert created.status_code == 201, created.text
    diagnostics: str = created.json()["issue"][0]["diagnostics"]
    return diagnostics


async def test_an_aggregate_receipt_names_its_form_unit_and_period(
    capture_client: httpx2.AsyncClient, aggregate_response: dict[str, Any]
) -> None:
    """The three facts an aggregate submission carries are all in the sentence, each named and identified."""
    diagnostics = await _diagnostics(capture_client, aggregate_response)

    assert "holding Child Health (BfMAe6Itzgt)" in diagnostics
    assert "reported from organisation unit Sierra Leone (ImspTQPwCqd)" in diagnostics
    assert "for period 202607" in diagnostics


async def test_a_receipt_keyed_to_an_attribute_option_combo_names_it(
    capture_client: httpx2.AsyncClient, attribute_combo_response: dict[str, Any]
) -> None:
    """A form on a non-default category combo says which of its option combos the values ride."""
    diagnostics = await _diagnostics(capture_client, attribute_combo_response)

    assert "keyed to attribute option combo" in diagnostics


async def test_a_tracker_receipt_states_no_period_it_does_not_report_for(
    capture_client: httpx2.AsyncClient, tracker_response: dict[str, Any]
) -> None:
    """A tracker event reports for no period, so the sentence carries no period clause at all."""
    diagnostics = await _diagnostics(capture_client, tracker_response)

    assert "reported from organisation unit" in diagnostics
    assert "for period" not in diagnostics


def test_the_sentence_leaves_out_every_fact_the_submission_does_not_carry() -> None:
    """A subject holding the form alone reads as the form alone - no empty clauses, no placeholders."""
    bare = CaptureSubject(form_id="BfMAe6Itzgt")

    assert capture_subject_sentence(bare) == "BfMAe6Itzgt"


def test_the_sentence_names_a_subject_this_server_publishes_no_name_for_by_its_identifier() -> None:
    """A unit the registry holds no name for is named by its UID rather than by an empty parenthesis."""
    subject = CaptureSubject(form_id="BfMAe6Itzgt", form_title="Child Health", organisation_unit_id="ImspTQPwCqd")

    assert capture_subject_sentence(subject) == (
        "Child Health (BfMAe6Itzgt), reported from organisation unit ImspTQPwCqd"
    )
