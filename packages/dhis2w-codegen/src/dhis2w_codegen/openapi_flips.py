"""Compare several captures of one DHIS2 OpenAPI document and list the pointers that differ."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

# Sections that name the server that answered, not the API it describes.
_IGNORED_TOP_LEVEL_KEYS = frozenset({"servers"})
_MISSING = "<absent>"


class Flip(BaseModel):
    """One JSON pointer whose value differs between captures."""

    model_config = ConfigDict(frozen=True)

    pointer: str
    variants: list[str]


class FlipReport(BaseModel):
    """Every pointer that differs across a set of captures of the same release."""

    model_config = ConfigDict(frozen=True)

    documents: list[Path]
    flips: list[Flip]

    def components(self) -> list[str]:
        """Return the distinct `components/schemas/<name>` and `paths/<path>` owners of the flips."""
        owners: list[str] = []
        for flip in self.flips:
            owner = "/".join(flip.pointer.split("/")[:4])
            if owner not in owners:
                owners.append(owner)
        return owners


def compare_documents(paths: list[Path]) -> FlipReport:
    """Load each capture and collect the pointers whose values are not identical across all of them."""
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    flips: list[Flip] = []
    top_level_keys = sorted({key for document in documents for key in document} - _IGNORED_TOP_LEVEL_KEYS)
    for key in top_level_keys:
        _collect(f"/{_escape(key)}", [document.get(key, _MISSING) for document in documents], flips)
    return FlipReport(documents=paths, flips=flips)


def render_text(report: FlipReport) -> str:
    """Render a report as one block per flipping pointer, one line per capture."""
    if not report.flips:
        return f"no differences across {len(report.documents)} captures"
    lines = [f"{len(report.flips)} pointers differ across {len(report.documents)} captures:"]
    for flip in report.flips:
        lines.append(f"  {flip.pointer}")
        for document, variant in zip(report.documents, flip.variants, strict=True):
            lines.append(f"    {document}: {variant[:200]}")
    return "\n".join(lines)


def _collect(pointer: str, values: list[Any], flips: list[Flip]) -> None:
    """Recurse into objects present in every capture; record any other disagreement at `pointer`."""
    if all(isinstance(value, dict) for value in values):
        keys = sorted({key for value in values for key in value})
        for key in keys:
            _collect(f"{pointer}/{_escape(key)}", [value.get(key, _MISSING) for value in values], flips)
        return
    rendered = [json.dumps(value, sort_keys=True) if value is not _MISSING else _MISSING for value in values]
    if len(set(rendered)) > 1:
        flips.append(Flip(pointer=pointer, variants=rendered))


def _escape(key: str) -> str:
    """Escape a key for use as a JSON-pointer segment (RFC 6901)."""
    return key.replace("~", "~0").replace("/", "~1")
