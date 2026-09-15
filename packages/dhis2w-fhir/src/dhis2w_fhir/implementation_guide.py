"""A compiled guide's own statement of what it published, read for the worked examples among them.

AN EXAMPLE IS NOT A PUBLISHED RESOURCE. A guide writes worked instances beside its profiles -
`Usage: #example` in FSH - so a reader of the published pages can see what one looks like, and SUSHI
compiles them into the same directory as everything else. The guide's own `ImplementationGuide`
resource is what tells the two apart: each entry of `definition.resource[]` states `exampleBoolean`
or `exampleCanonical` for an instance that illustrates a profile rather than publishing a fact.

Two readers ask that question of the same declaration, so both ask it here. `d2w fhir serve` holds
the declared examples out of what it searches and counts, and the drift phase of `d2w fhir doctor`
holds them out of what it grades: the exemplar organisation unit this toolchain mints carries the
identifier `d2-example`, which belongs to no organisation unit anywhere, so grading it against an
instance would report a removal no DHIS2 administrator can act on and no regeneration can clear.

A guide that states nothing - a project served before its first compile wrote one, a store built
from an instance - declares no example, and everything it holds is published. A guide resource that
cannot be read costs its own declarations and is named on `unreadable_guides`: one malformed
document never decides what a whole guide publishes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dhis2w_fhir.conversion.artifacts import COMPILED_RESOURCES_RELATIVE_PATH
from dhis2w_fhir.r4 import Reference

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from dhis2w_fhir.config import FhirProject

__all__ = [
    "IMPLEMENTATION_GUIDE_RESOURCE_TYPE",
    "DeclaredExamples",
    "GuideDocument",
    "ImplementationGuideContents",
    "ImplementationGuideDefinition",
    "ImplementationGuideResource",
    "PublishedResourceKey",
    "declared_examples",
    "load_declared_examples",
    "reference_key",
]

#: The resource type a guide states its own contents on, and where the examples among them are named.
IMPLEMENTATION_GUIDE_RESOURCE_TYPE = "ImplementationGuide"


class PublishedResourceKey(BaseModel):
    """One resource as a published tree indexes it: its FHIR type and its resource id."""

    model_config = ConfigDict(frozen=True)

    resource_type: str
    resource_id: str

    @property
    def reference(self) -> str:
        """The `{type}/{id}` reference this key reads back as, for naming it in a report or a log line."""
        return f"{self.resource_type}/{self.resource_id}"


class GuideDocument(BaseModel):
    """One wire document an example declaration is read from, with whatever names it in a diagnostic."""

    model_config = ConfigDict(frozen=True)

    source: str
    """Where the document came from: a file path, or whatever else the caller indexes it by."""

    body: dict[str, Any]
    """The resource verbatim, on the same terms every other reader of a published tree holds one.

    A caller already holds its documents as the JSON it read them from - a store entry, a compiled
    file, a registry archive member - and this is the JSON boundary that reading ends at: the dict
    is validated into `ImplementationGuideContents` here and reaches no other module as a dict.
    """


class ImplementationGuideResource(BaseModel):
    """One resource an `ImplementationGuide` lists, and whether the guide calls it an example.

    R4 spells the answer two ways on the same element: `exampleBoolean` says "this illustrates
    something" and `exampleCanonical` says which profile it illustrates. Either one names an example,
    and `exampleBoolean = false` - which SUSHI writes on every published instance - names none.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    reference: Reference | None = None
    example_boolean: bool | None = Field(default=None, alias="exampleBoolean")
    example_canonical: str | None = Field(default=None, alias="exampleCanonical")

    def is_example(self) -> bool:
        """Whether the guide states this entry illustrates a profile rather than publishing a fact."""
        return self.example_boolean is True or self.example_canonical is not None


class ImplementationGuideDefinition(BaseModel):
    """What a guide states it contains, of which the resource list alone is read here."""

    model_config = ConfigDict(extra="allow")

    resource: tuple[ImplementationGuideResource, ...] = ()


class ImplementationGuideContents(BaseModel):
    """A guide's own statement of what it published, read for the examples among them.

    `extra="allow"` throughout: an `ImplementationGuide` carries pages, dependencies, parameters and
    a template no reader here has a use for, and a guide is served byte-faithfully whatever else it
    holds. Only `definition.resource[]` is read.
    """

    model_config = ConfigDict(extra="allow")

    definition: ImplementationGuideDefinition | None = None

    def example_references(self) -> tuple[str, ...]:
        """Every `{type}/{id}` reference the guide declares as an example, in the order it lists them."""
        if self.definition is None:
            return ()
        return tuple(
            declared.reference.reference
            for declared in self.definition.resource
            if declared.is_example() and declared.reference is not None and declared.reference.reference
        )


class DeclaredExamples(BaseModel):
    """The worked examples one set of published documents declares, and the guides that could not be read."""

    model_config = ConfigDict(frozen=True)

    keys: frozenset[PublishedResourceKey] = frozenset()
    """One key per declared example, as the read index of a published tree keys it."""

    unreadable_guides: tuple[str, ...] = ()
    """One line per `ImplementationGuide` whose contents could not be read, naming its source."""

    def declares(self, resource_type: str, resource_id: str | None) -> bool:
        """Whether the guide calls that resource a worked example rather than something it publishes."""
        if resource_id is None:
            return False
        return PublishedResourceKey(resource_type=resource_type, resource_id=resource_id) in self.keys

    def publishes(self, resource_type: str, resource_id: str | None) -> bool:
        """Whether that resource is one the guide publishes, which a worked example it merely holds is not."""
        return not self.declares(resource_type, resource_id)

    @property
    def references(self) -> tuple[str, ...]:
        """Every declared example as `{type}/{id}`, sorted, for naming them in one line."""
        return tuple(sorted(key.reference for key in self.keys))


def declared_examples(documents: Iterable[GuideDocument]) -> DeclaredExamples:
    """Every instance the `ImplementationGuide`s among these documents name as a worked example."""
    keys: set[PublishedResourceKey] = set()
    unreadable: list[str] = []
    for document in documents:
        if document.body.get("resourceType") != IMPLEMENTATION_GUIDE_RESOURCE_TYPE:
            continue
        try:
            guide = ImplementationGuideContents.model_validate(document.body)
        except ValidationError as error:
            unreadable.append(f"{document.source}: ImplementationGuide states contents that cannot be read ({error})")
            continue
        keys.update(key for key in map(reference_key, guide.example_references()) if key is not None)
    return DeclaredExamples(keys=frozenset(keys), unreadable_guides=tuple(unreadable))


def load_declared_examples(project: FhirProject) -> DeclaredExamples:
    """Read the worked examples one project's published trees declare, off the guides compiled into them.

    Both trees `d2w fhir serve` serves are read - `ig/fsh-generated/resources` for what the compiler
    wrote and `ig/input/resources` for the predefined tree the emitters wrote straight to JSON -
    because a hand-written `ImplementationGuide` in the second one states its contents as much as a
    compiled one does. A registry package publishes `Location` and `Organization` alone, so a
    depending guide gains no declaration from it and none is read.

    A file this cannot read as JSON is passed over rather than refused: `load_compiled_artifacts`
    reads the same trees and already refuses such a file loudly, naming it.
    """
    compiled_directory = project.ig_directory / COMPILED_RESOURCES_RELATIVE_PATH
    predefined_directory = project.resources_directory
    paths = [
        *(sorted(compiled_directory.glob("*.json")) if compiled_directory.is_dir() else []),
        *(sorted(predefined_directory.rglob("*.json")) if predefined_directory.is_dir() else []),
    ]
    return declared_examples(document for document in map(_guide_document, paths) if document is not None)


def reference_key(reference: str) -> PublishedResourceKey | None:
    """One `{type}/{id}` reference as the key a read index holds it under, relative or absolute alike.

    A guide publishing its own contents writes `Location/<id>`, and one writing a resource under the
    canonical it will be published at writes `<canonical>/Location/<id>`. Both name one resource, so
    the last two segments are the key either way.
    """
    segments = [segment for segment in reference.split("/") if segment]
    if len(segments) < 2:
        return None
    return PublishedResourceKey(resource_type=segments[-2], resource_id=segments[-1])


def _guide_document(path: Path) -> GuideDocument | None:
    """One published file as a guide document, or None for a file holding no `ImplementationGuide`.

    The text is searched before it is parsed. A document that never spells the type cannot be one,
    and a published tree is mostly Locations and Questionnaires - so the tree is read once and
    parsed hardly at all.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if IMPLEMENTATION_GUIDE_RESOURCE_TYPE not in text:
        return None
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return None
    return GuideDocument(source=str(path), body=body) if isinstance(body, dict) else None
