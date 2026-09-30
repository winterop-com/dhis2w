"""Unit tests for comparing several captures of one OpenAPI document."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dhis2w_codegen.openapi_flips import compare_documents, render_text


def _write(tmp_path: Path, name: str, document: dict[str, Any]) -> Path:
    """Write one capture to disk and return its path."""
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _capture(aggregation_type: dict[str, Any], server: str) -> dict[str, Any]:
    """Build a minimal capture whose `CategoryOption.aggregationType` is the given schema."""
    return {
        "openapi": "3.0.0",
        "servers": [{"url": server}],
        "paths": {"/api/me": {"get": {"operationId": "me"}}},
        "components": {
            "schemas": {
                "CategoryOption": {"type": "object", "properties": {"aggregationType": aggregation_type}},
                "Instant": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            },
        },
    }


def test_identical_captures_report_nothing(tmp_path: Path) -> None:
    """Captures that differ only in `servers` have no flips."""
    first = _write(tmp_path, "a.json", _capture({"type": "boolean"}, "http://one/"))
    second = _write(tmp_path, "b.json", _capture({"type": "boolean"}, "http://two/"))

    report = compare_documents([first, second])

    assert report.flips == []
    assert render_text(report) == "no differences across 2 captures"


def test_flip_is_reported_at_the_deepest_disagreeing_pointer(tmp_path: Path) -> None:
    """A property typed two ways is reported once, with one variant per capture."""
    reference = {"$ref": "#/components/schemas/AggregationType"}
    first = _write(tmp_path, "a.json", _capture(reference, "http://one/"))
    second = _write(tmp_path, "b.json", _capture({"type": "boolean"}, "http://one/"))

    report = compare_documents([first, second])

    assert [flip.pointer for flip in report.flips] == [
        "/components/schemas/CategoryOption/properties/aggregationType/$ref",
        "/components/schemas/CategoryOption/properties/aggregationType/type",
    ]
    assert report.flips[0].variants == ['"#/components/schemas/AggregationType"', "<absent>"]
    assert report.components() == ["/components/schemas/CategoryOption"]


def test_pointer_segments_are_escaped(tmp_path: Path) -> None:
    """Path keys containing `/` are escaped per RFC 6901."""
    first_document = _capture({"type": "boolean"}, "http://one/")
    second_document = _capture({"type": "boolean"}, "http://one/")
    second_document["paths"]["/api/me"]["get"]["operationId"] = "me2"
    report = compare_documents(
        [_write(tmp_path, "a.json", first_document), _write(tmp_path, "b.json", second_document)]
    )

    assert [flip.pointer for flip in report.flips] == ["/paths/~1api~1me/get/operationId"]
