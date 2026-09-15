"""What the capture path says back: one issue vocabulary, and the two OperationOutcomes it builds.

A capture answers with an OperationOutcome whether it succeeded or not, because a response the
server accepted with warnings is the interesting case: the submission is stored, and the client
still has to be told what the server could not check or had to interpret. Rejections and
acceptances therefore share one issue type, and differ only in the severity they carry.

The issue codes are R4's own (`OperationOutcome.issue.code`), narrowed to the ones a capture can
raise. They are wider than the read path's vocabulary in `errors.py` on purpose: a read either
finds a resource or does not, while a capture fails against a profile, a terminology, or a
questionnaire's own item tree, and R4 names those failures separately.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from dhis2w_fhir.r4 import OperationOutcome, OperationOutcomeIssue
from pydantic import BaseModel, ConfigDict

from dhis2w_fhir_serve.capture.index import LOCATION_RESOURCE_TYPE

if TYPE_CHECKING:
    from dhis2w_fhir_serve.capture.validate import CaptureSubject

CaptureIssueSeverity = Literal["error", "warning", "information"]
"""The `OperationOutcome.issue.severity` values a capture reports."""

CaptureIssueCode = Literal[
    "invalid",
    "structure",
    "required",
    "value",
    "invariant",
    "code-invalid",
    "multiple-matches",
    "not-found",
    "not-supported",
    "business-rule",
    "informational",
]
"""The `OperationOutcome.issue.code` values a capture reports."""

#: What the information issue on an accepted capture states about what was stored.
RECEIPT_NOTE = "a stored response is the submission as received - a receipt, not a live view of DHIS2 data"


class CaptureIssue(BaseModel):
    """One thing the capture path found: where it is, what it is, and how badly it went."""

    model_config = ConfigDict(frozen=True)

    severity: CaptureIssueSeverity
    code: CaptureIssueCode
    expression: str | None = None
    diagnostics: str | None = None

    def is_error(self) -> bool:
        """Whether this issue rejects the submission rather than annotating it."""
        return self.severity == "error"


class CaptureRejection(Exception):
    """A submission the facade refused, carrying the status it answers with and every issue found."""

    def __init__(self, http_status: int, issues: tuple[CaptureIssue, ...]) -> None:
        super().__init__(f"capture rejected with {http_status}: {len(issues)} issue(s)")
        self.http_status = http_status
        self.issues = issues


def rejection_outcome(issues: tuple[CaptureIssue, ...]) -> OperationOutcome:
    """The body a refused capture answers with: every issue the failing phase found, in the order found."""
    return OperationOutcome(issue=[_issue(issue) for issue in issues])


def success_outcome(response_id: str, subject: CaptureSubject, warnings: tuple[CaptureIssue, ...]) -> OperationOutcome:
    """The body an accepted capture answers with: what was stored, then whatever the server had to note."""
    stored = OperationOutcomeIssue(
        severity="information",
        code="informational",
        diagnostics=f"stored response {response_id}, holding {capture_subject_sentence(subject)}; {RECEIPT_NOTE}",
    )
    return OperationOutcome(issue=[stored, *(_issue(warning) for warning in warnings)])


def capture_subject_sentence(subject: CaptureSubject) -> str:
    """Name the four facts a forward grades a receipt by, in the order DHIS2 keys a value it writes by.

    A UUID tells a client which receipt was stored and nothing about what is in it, so a session that
    posted thirty-two drafts reads thirty-two indistinguishable lines. The tuple is what separates
    them, and it is the same tuple the receipt page's capture context states and the same one a drain
    reports a refusal against.

    A clause is written where the submission holds the fact and left out where it does not: a tracker
    response reports for no period, and a form on the default category combo is keyed to no attribute
    option combo.
    """
    clauses = [f"{_named(subject.form_title, subject.form_id)}"]
    if subject.organisation_unit_id is not None:
        clauses.append(f"reported from {_organisation_unit_clause(subject)}")
    if subject.period is not None:
        clauses.append(f"for period {subject.period}")
    if subject.attribute_option_combo_code is not None:
        named = _named(subject.attribute_option_combo_display, subject.attribute_option_combo_code)
        clauses.append(f"keyed to attribute option combo {named}")
    return ", ".join(clauses)


def _organisation_unit_clause(subject: CaptureSubject) -> str:
    """Name the organisation unit a receipt reports from, or say that this guide publishes none such.

    THE PARENTHETICAL IS LABELLED BECAUSE IT IS NOT ALWAYS A UID. A guide naming its organisation
    units by their DHIS2 code publishes `Location/OU-226264`, and the same parenthetical in an
    id-stemmed guide is the DHIS2 UID - so it is written as the reference it is, and a reader holding
    one knows which of the two they have without having to know how the guide was generated.

    A unit this guide publishes no Location for gets no name because there is none to have, and
    printing the id where a name goes would read as a unit whose name went missing rather than as
    the finding it is. So the clause says what is true of it instead.
    """
    reference = f"{LOCATION_RESOURCE_TYPE}/{subject.organisation_unit_id}"
    if subject.organisation_unit_standing == "unpublished":
        return f"an organisation unit this guide does not publish ({reference})"
    return f"organisation unit {_named(subject.organisation_unit_name, reference)}"


def _named(display: str | None, identifier: str) -> str:
    """One subject as `name (id)`, or as the identifier alone where this server publishes no name for it."""
    return identifier if display is None else f"{display} ({identifier})"


def _issue(issue: CaptureIssue) -> OperationOutcomeIssue:
    """Carry one capture issue onto the R4 element it is reported as."""
    return OperationOutcomeIssue(
        severity=issue.severity,
        code=issue.code,
        diagnostics=issue.diagnostics,
        expression=[issue.expression] if issue.expression else None,
    )
