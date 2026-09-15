"""The generate-time build refusal, read off the disk a build publishes from.

`d2w fhir generate` refuses a run whose selected DHIS2 names or codes carry a `<`: the IG publisher
writes both into pages it strict-parses after writing, and dies on the malformed page in its final
pass, once every resource has already been rendered. That gate stands at the emit site, and a build
never visits the emit site - `make build` publishes whatever `ig/fsh-generated/` and `ig/input/`
hold. Artifacts written before the gate existed, artifacts from a generate an older lock pinned, and
hand-authored FSH all reach the publisher without passing it, and cost a full publisher run to find.

This module is the same refusal applied to those files. It reads the publishable inputs on disk,
checks the string positions the four emit-site gates check, and names the file, the resource, the
element, and the value - so what a reader gets back is the object, rather than the page the
publisher happened to die on. It opens no connection and reads no profile: the artifacts are the
whole input, which is why it answers in seconds and answers on a plane.

The predicates are `build_aborting_name` and `build_aborting_code` themselves, imported from this
package rather than restated, so a disk scan and an emit-site refusal can never disagree about which
character the publisher cannot survive.

## What is read

- `ig/fsh-generated/**/*.json` - what SUSHI compiled, which is what the publisher publishes.
- `ig/input/resources/**/*.json` - the registry, terminology, and ConceptMap documents the generate
  targets write straight to JSON, which the compile step copies through untouched.
- `ig/input/fsh/**/*.fsh` - the FSH sources, generated and hand-authored alike. A hand-authored file
  passes no other gate in this toolchain.
- `fhir.toml` and `ig/sushi-config.yaml` - the guide's own identity, which no DHIS2 selection
  supplies and no compiled resource carries until SUSHI has run. A title carrying a `<` reaches the
  ImplementationGuide resource and the pages rendered from it, so the publisher dies on it exactly
  as it dies on a DHIS2 name - and on a project that has only run `generate` there is nothing else
  on disk to find it in.

`ig/input/pagecontent/**/*.md` is deliberately left out. Markdown carries HTML by design, so a `<`
there is the page's own markup rather than a DHIS2 name that escaped.

## What a finding is answered by

Every finding carries its `origin` - where the offending value came from - and the remedy follows
from it rather than from a guess made while printing. A DHIS2 name is renamed in DHIS2 or dropped
from the selection; the guide's identity is changed in the `[ig]` table of `fhir.toml` and landed
with `d2w fhir init --refresh`; a hand-authored source is edited, because nothing regenerates one.
Naming the wrong one costs a reader the afternoon they spend looking for a DHIS2 object that does
not exist.

## Severity

Most findings are build-aborting and exit the command 1, which is what `make build` runs it for.
Three are warnings: a published form whose organisation-unit assignment names no organisation unit
the project publishes, a published form whose whole attribute-combo vocabulary DHIS2 restricts away
from every organisation unit the project publishes, and a `[generate.*] include_ids` entry the
published tree carries no trace of. All three builds are valid and will publish - the first two
publish a form nobody can submit a response to, on the two axes DHIS2 grades a capture by, the third
a guide missing the very form the entry asked for - and all three are worth a look before the
publisher is paid for.

## What is checked, and why exactly this

One position per emit-site gate, so the disk scan refuses what generate refuses and nothing else:

| Position | Emit-site gate it mirrors | Where the publisher dies on it |
| --- | --- | --- |
| `name`, `title` | `_refuse_build_aborting_objects`, on the object's name | breadcrumbs and change-history headings |
| `display` | `_refuse_build_aborting_member_names` | the concept tables of a CodeSystem or ValueSet page |
| `text` | `_refuse_build_aborting_question_names` | the question rows of a Questionnaire page |
| `identifier[].value` | `_refuse_build_aborting_objects`, on the code | the identifier table cell, written raw |

A resource's `description` is not checked, for the same reason the emit-site gates do not check one:
adding a position here that generate does not refuse would make one gate call clean what the other
refuses, which is the disagreement both exist to prevent. The IG's own `description` in
`ig/sushi-config.yaml` is a different string with no emit-site gate behind it at all - no DHIS2
object supplies it, so there is nothing for this to disagree with, and the publisher renders it on
the guide's front matter like any other identity value.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from dhis2w_fhir.config import FHIR_CONFIG_FILENAME
from dhis2w_fhir.period import PERIOD_TYPE_NAMES
from dhis2w_fhir.period.parser import parse_period
from dhis2w_fhir.period.recent import recent_periods
from dhis2w_fhir.registry_package import RegistryMissingError, load_registry_documents
from dhis2w_fhir.resources.attribute_combos.restrictions import (
    ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
    ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE,
    ATTRIBUTE_OPTION_VALID_FROM_PROPERTY,
    ATTRIBUTE_OPTION_VALID_TO_PROPERTY,
    UNTIMELY_ATTRIBUTE_OPTION_COMBO_REMEDY,
    UNUSABLE_ATTRIBUTE_OPTION_COMBO_REMEDY,
    CategoryOptionValidity,
)
from dhis2w_fhir.resources.attribute_combos.schemas import ATTRIBUTE_COMBO_DIRECTORY
from dhis2w_fhir.resources.questionnaires.assignments import (
    ASSIGNMENT_DIRECTORY,
    ASSIGNMENT_LIST_RESOURCE_TYPE,
    EMPTY_ASSIGNMENT_REMEDY,
)
from dhis2w_fhir.scaffold import SUSHI_CONFIG_RELATIVE_PATH
from dhis2w_fhir.validation import build_aborting_code, build_aborting_name
from dhis2w_fhir.writer import is_generated_file

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from dhis2w_fhir.config import FhirProject
    from dhis2w_fhir.period.schemas import PeriodValue

__all__ = [
    "ArtifactCheckReport",
    "ArtifactFinding",
    "FindingOrigin",
    "check_publishable_artifacts",
]

#: The JSON element names whose string value is a DHIS2 name kept byte-true on the emitted resource.
#: One per emit-site gate surface: `name` and `title` carry an object's own name, `display` carries
#: an option, a category option, or a data dictionary concept, and `text` carries a question's label.
#: Only a string value is read, so a DomainResource's `text` - a `Narrative` object whose `div` is
#: HTML by contract - is never mistaken for one of these.
_NAME_ELEMENTS = frozenset({"name", "title", "display", "text"})

#: The element whose members carry a DHIS2 code as an emitted identifier value.
_IDENTIFIER_ELEMENT = "identifier"

#: The element of an `Identifier` holding the code itself.
_VALUE_ELEMENT = "value"

#: The trees a publisher run reads its resources out of, relative to the IG directory, in scan order.
_JSON_TREES = ("fsh-generated", "input/resources")

#: The tree the FSH sources live in, relative to the IG directory.
_FSH_TREE = "input/fsh"

#: The element every FHIR resource names its type in. A JSON file without one is not something the
#: publisher renders a page for, so no name inside it can abort a build.
_RESOURCE_TYPE_ELEMENT = "resourceType"

#: What a resource without an `id` is named in a finding - the file already names it, and a
#: contained or bundled resource may legitimately carry none.
_UNIDENTIFIED_RESOURCE = "(no id)"

#: One FSH assignment rule, `* <path> = "<value>"`, with the escaped quotes a value may carry.
_FSH_ASSIGNMENT = re.compile(r'^\s*\*\s+(?P<path>[^=]+?)\s*=\s*"(?P<value>(?:[^"\\]|\\.)*)"')

#: One FSH concept rule, `* #<code> "<display>"`, including the `* include #<code> "<display>"` form.
_FSH_CONCEPT = re.compile(r'^\s*\*\s+(?:[^"#]*\s)?#(?P<code>[^\s"]+)\s+"(?P<display>(?:[^"\\]|\\.)*)"')

#: One FSH `Title:` keyword line, which becomes the entity's `title` element.
_FSH_TITLE = re.compile(r'^\s*Title:\s*"(?P<value>(?:[^"\\]|\\.)*)"')

#: One FSH entity declaration, whose name is what a finding inside that entity is reported under.
_FSH_DECLARATION = re.compile(
    r"^(?P<keyword>Alias|CodeSystem|Extension|Instance|Invariant|Logical|Mapping|Profile|Resource|RuleSet|ValueSet):"
    r"\s*(?P<name>\S+)"
)

#: What an entity-less FSH finding is reported under - a rule before any declaration in the file.
_UNDECLARED_ENTITY = "(file)"

#: The FSH path segment a code finding has to sit under, mirroring `identifier[].value` in JSON.
_FSH_IDENTIFIER_SEGMENT = "identifier"

#: The field name a `Title:` keyword finding carries, so the report names the FSH line a reader edits.
_FSH_TITLE_FIELD = "Title:"

#: Why a name aborts the publisher, in the words the emit-site refusal uses. Stated once per finding
#: on the report and once per kind on the terminal, because it is the same cost every time.
_NAME_MESSAGE = (
    "a name carrying '<' stays byte-true on the resource, and the IG publisher writes it into pages it "
    "strict-parses after writing, so `make build` aborts in its last pass, once every resource has "
    "already been rendered."
)

#: Why an identifier value aborts the publisher, in the words the emit-site refusal uses.
_CODE_MESSAGE = (
    "an identifier value carrying '<' reaches a table cell the IG publisher writes unescaped and then "
    "strict-parses, so `make build` aborts in its last pass, once every resource has already been rendered."
)


class FindingOrigin(StrEnum):
    """Where an offending value came from, which is the fact the line answering it follows from."""

    DHIS2 = "dhis2"
    """A DHIS2 name or code, carried byte-true into an artifact this toolchain generated."""

    IG_IDENTITY = "ig-identity"
    """The guide's own identity - the `[ig]` table of fhir.toml, and the sushi-config written from it."""

    AUTHORED = "authored"
    """A hand-authored source, which nothing regenerates."""

    REGISTRY_SELECTION = "registry-selection"
    """A reference into the organisation-unit registry package for a unit that package does not publish."""

    REGISTRY_MISSING = "registry-missing"
    """The registry package a guide depends on, which the scan could not read at all."""

    ASSIGNMENT = "assignment"
    """A published form whose organisation-unit assignment names no organisation unit this project publishes."""

    ATTRIBUTE_OPTION_COMBO = "attribute-option-combo"
    """A published form every attribute option combo of whose vocabulary is restricted away from every unit."""

    UNTIMELY_ATTRIBUTE_OPTION_COMBO = "untimely-attribute-option-combo"
    """A published form every attribute option combo of whose vocabulary DHIS2 closed before the periods it reports."""

    SELECTION = "selection"
    """A `[generate.*] include_ids` entry naming a DHIS2 object this project publishes nothing for."""


FindingSeverity = Literal["build-aborting", "warning"]
"""Whether a finding stops the build or only asks to be looked at before one is paid for."""

#: The fix for a file this toolchain wrote: the object is wrong in DHIS2, and the artifacts follow from it.
_GENERATED_REMEDY = "Rename it in DHIS2 or narrow the selection in fhir.toml, then run `d2w fhir generate` again."

#: The fix for a hand-authored file: nothing regenerates it, so the file itself is where the '<' goes.
_AUTHORED_REMEDY = "Edit the file and remove the '<' - nothing regenerates a hand-authored source."

#: The fix for the guide's own identity, which fhir.toml states and a refresh lands in every file carrying it.
_IG_IDENTITY_REMEDY = "Change `[ig] {key}` in fhir.toml, then run `d2w fhir init --refresh`."

#: The fix for an identity value sushi-config states that no `[ig]` key spells directly, such as the
#: description the scaffold derives from the title.
_IG_IDENTITY_DERIVED_REMEDY = (
    "Change the `[ig]` table in fhir.toml, then run `d2w fhir init --refresh` - "
    "ig/sushi-config.yaml is written from it."
)

#: What answers a dangling registry reference: the two projects disagree about the selection.
_REGISTRY_REMEDY = (
    "regenerate both projects against the same instance - the guide's "
    "[generate.organisation_units] selection and the registry package's have gone apart"
)

#: What answers a registry the scan could not read at all.
_REGISTRY_UNREADABLE_REMEDY = (
    "run `d2w fhir generate` in the registry checkout `path` names, or pass "
    "`--registry-package <package.tgz>` so the scan can read what the package publishes"
)

#: What answers a form nobody can submit: the registry is narrower than the forms DHIS2 assigns. The
#: one sentence `d2w fhir generate` closes such a run with, so both commands prescribe one thing.
_ASSIGNMENT_REMEDY = EMPTY_ASSIGNMENT_REMEDY

#: What answers a selection entry the guide publishes nothing for: the UID and the instance disagree.
_SELECTION_REMEDY = (
    "Check the UID in the DHIS2 Maintenance app, then correct it in the include_ids table this row "
    "names - or drop it - and run `d2w fhir generate` again."
)

#: The line each origin is answered by, stated once. `ig-identity` is not here: its line names the
#: key the value is stated under, so it is rendered from the finding rather than looked up.
_ORIGIN_REMEDIES: dict[FindingOrigin, str] = {
    FindingOrigin.DHIS2: _GENERATED_REMEDY,
    FindingOrigin.AUTHORED: _AUTHORED_REMEDY,
    FindingOrigin.REGISTRY_SELECTION: _REGISTRY_REMEDY,
    FindingOrigin.REGISTRY_MISSING: _REGISTRY_UNREADABLE_REMEDY,
    FindingOrigin.ASSIGNMENT: _ASSIGNMENT_REMEDY,
    FindingOrigin.ATTRIBUTE_OPTION_COMBO: UNUSABLE_ATTRIBUTE_OPTION_COMBO_REMEDY,
    FindingOrigin.UNTIMELY_ATTRIBUTE_OPTION_COMBO: UNTIMELY_ATTRIBUTE_OPTION_COMBO_REMEDY,
    FindingOrigin.SELECTION: _SELECTION_REMEDY,
}

#: The origins whose finding lets the build run. Four, and for the same reason: a form nobody can
#: submit - on any of the three axes DHIS2 grades a capture by - and a selection entry that named
#: nothing all publish perfectly well, so stopping the build over one would refuse a guide the
#: publisher has no quarrel with.
_WARNING_ORIGINS = frozenset(
    {
        FindingOrigin.ASSIGNMENT,
        FindingOrigin.ATTRIBUTE_OPTION_COMBO,
        FindingOrigin.UNTIMELY_ATTRIBUTE_OPTION_COMBO,
        FindingOrigin.SELECTION,
    }
)


class ArtifactFinding(BaseModel):
    """One on-disk string a build is worth stopping for: where it sits, what it says, what to do."""

    model_config = ConfigDict(frozen=True)

    file: str
    """The offending file, relative to the project root."""

    resource_id: str
    """The resource the string sits on - a FHIR `id` in JSON, a declared entity name in FSH."""

    field: str
    """The element the string sits at, e.g. `title`, `concept[3].display`, `identifier[0].value`."""

    value: str
    """The offending string, byte-true, so a reader can search the instance for it."""

    kind: Literal["name", "code", "registry", "assignment", "attribute-option-combo", "selection"]
    """What raised it: a DHIS2 name, a DHIS2 code emitted as an identifier, a registry reference, an
    assignment, an attribute option combo vocabulary, or a selection entry."""

    origin: FindingOrigin
    """Where the value came from, which is what the remedy and the severity are read off."""

    ig_key: str | None = None
    """The `[ig]` key the value is stated under, for an identity value fhir.toml spells directly."""

    message: str
    """Why the finding is worth a build, in the words the generate-time refusal uses."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> FindingSeverity:
        """Whether this finding stops the build or is a note on a build that would publish."""
        return "warning" if self.origin in _WARNING_ORIGINS else "build-aborting"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def remedy(self) -> str:
        """The one line the finding is answered by, which follows from where the value came from."""
        if self.origin is not FindingOrigin.IG_IDENTITY:
            return _ORIGIN_REMEDIES[self.origin]
        return _IG_IDENTITY_DERIVED_REMEDY if self.ig_key is None else _IG_IDENTITY_REMEDY.format(key=self.ig_key)


class ArtifactCheckReport(BaseModel):
    """What one scan of a project's publishable inputs read, and everything it raises about them."""

    model_config = ConfigDict(frozen=True)

    project_root: str
    json_file_count: int = 0
    fsh_file_count: int = 0
    unreadable_files: list[str] = Field(default_factory=list)
    """Files under a scanned tree whose bytes are not JSON at all, named rather than passed over in silence."""

    findings: list[ArtifactFinding] = Field(default_factory=list)

    @property
    def finding_count(self) -> int:
        """How many findings the scan raised, of either severity."""
        return len(self.findings)

    @property
    def build_aborting_count(self) -> int:
        """How many findings stop the build; zero is a build that may start."""
        return sum(1 for finding in self.findings if finding.severity == "build-aborting")

    @property
    def warning_count(self) -> int:
        """How many findings sit on a build that would publish anyway."""
        return sum(1 for finding in self.findings if finding.severity == "warning")

    @property
    def file_count(self) -> int:
        """How many publishable files the scan read, across both formats."""
        return self.json_file_count + self.fsh_file_count

    @property
    def messages(self) -> list[str]:
        """One line per kind of build abort present, in finding order - the cost stated once, not per row."""
        seen: list[str] = []
        for finding in self.findings:
            if finding.message not in seen:
                seen.append(finding.message)
        return seen


class _HostileString(BaseModel):
    """One build-aborting string found inside a document, before the file that holds it names it."""

    model_config = ConfigDict(frozen=True)

    field: str
    value: str
    kind: Literal["name", "code"]


def check_publishable_artifacts(
    project: FhirProject, *, registry_package: Path | None = None, today: date | None = None
) -> ArtifactCheckReport:
    """Scan one project's on-disk publishable inputs for every string the IG publisher would abort on.

    Offline and connectionless: the artifacts are the whole input. Findings sort by file, then by
    resource, then by element, so two runs over one unchanged tree read identically.

    The guide's own identity is scanned alongside the artifacts, so a title carrying a `<` is found
    on a project that has only run `generate` - before SUSHI compiles the ImplementationGuide the
    publisher would otherwise die on it in.

    A guide depending on an organisation-unit registry package is additionally checked against what
    that package publishes, so a reference to a unit it does not carry is caught here rather than by
    the publisher after it has rendered everything else. `registry_package` names the archive when
    no checkout answers, exactly as it does for the facade.
    """
    root = project.project_root
    json_paths = _json_paths(project)
    fsh_paths = _fsh_paths(project)
    findings: list[ArtifactFinding] = []
    unreadable: list[str] = []
    for path in json_paths:
        document = _read_document(path)
        if document is None:
            unreadable.append(_relative(path, root))
            continue
        findings.extend(_findings_in_document(document, path, root))
    for path in fsh_paths:
        findings.extend(_findings_in_fsh(path, root))
    findings.extend(_ig_identity_findings(project))
    findings.extend(_empty_assignment_findings(project, root))
    findings.extend(_unusable_attribute_option_combo_findings(project, root))
    findings.extend(_untimely_attribute_option_combo_findings(project, root, today or datetime.now(tz=UTC).date()))
    findings.extend(_selection_findings(project))
    findings.extend(_registry_findings(project, root, registry_package))
    findings.sort(key=lambda finding: (finding.file, finding.resource_id, finding.field))
    return ArtifactCheckReport(
        project_root=str(root),
        json_file_count=len(json_paths),
        fsh_file_count=len(fsh_paths),
        unreadable_files=unreadable,
        findings=findings,
    )


def _json_paths(project: FhirProject) -> list[Path]:
    """Every JSON file a publisher run would read, compiled output first, then the pre-built tree."""
    paths: list[Path] = []
    for tree in _JSON_TREES:
        directory = project.ig_directory / tree
        if directory.is_dir():
            paths.extend(sorted(directory.rglob("*.json")))
    return paths


def _fsh_paths(project: FhirProject) -> list[Path]:
    """Every FSH source in the project, at any depth, generated and hand-authored alike."""
    directory = project.fsh_directory
    return sorted(directory.rglob("*.fsh")) if directory.is_dir() else []


def _read_document(path: Path) -> Any | None:  # noqa: ANN401 - a JSON file is whatever it holds
    """Parse one file as JSON, or None when the bytes on disk are not JSON at all."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _findings_in_document(document: Any, path: Path, root: Path) -> list[ArtifactFinding]:  # noqa: ANN401 - JSON
    """Every build-aborting string in one JSON document, named by the resource and element holding it.

    Anything that is not an object carrying a `resourceType` is passed over: the publisher renders no
    page for it, so no string inside it can abort a build. The SUSHI index beside the compiled
    resources is the file that reaches this, and it is bookkeeping rather than a defect.
    """
    if not isinstance(document, dict) or not isinstance(document.get(_RESOURCE_TYPE_ELEMENT), str):
        return []
    resource_id = document.get("id")
    named = resource_id if isinstance(resource_id, str) else _UNIDENTIFIED_RESOURCE
    return [
        ArtifactFinding(
            file=_relative(path, root),
            resource_id=named,
            field=hostile.field,
            value=hostile.value,
            kind=hostile.kind,
            origin=FindingOrigin.DHIS2,
            message=_message(hostile.kind),
        )
        for hostile in _walk(document, prefix="", in_identifier=False)
    ]


def _walk(node: Any, *, prefix: str, in_identifier: bool) -> Iterator[_HostileString]:  # noqa: ANN401 - JSON is Any
    """Yield every build-aborting string under one JSON node, carrying the element path down to it."""
    if isinstance(node, dict):
        for key, value in node.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk(value, prefix=field, in_identifier=in_identifier or key == _IDENTIFIER_ELEMENT)
        return
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from _walk(item, prefix=f"{prefix}[{index}]", in_identifier=in_identifier)
        return
    if isinstance(node, str):
        element = prefix.rsplit(".", 1)[-1]
        if element in _NAME_ELEMENTS and build_aborting_name(node):
            yield _HostileString(field=prefix, value=node, kind="name")
        elif in_identifier and element == _VALUE_ELEMENT and build_aborting_code(node):
            yield _HostileString(field=prefix, value=node, kind="code")


def _findings_in_fsh(path: Path, root: Path) -> list[ArtifactFinding]:
    """Every build-aborting string in one FSH source, named by the entity and rule holding it.

    FSH is read line by line rather than parsed: the positions that matter are single-line rules,
    and a line scan costs nothing on a tree of hundreds of files. A triple-quoted multi-line string
    value, which no generate target emits, is not read.
    """
    origin = FindingOrigin.DHIS2 if is_generated_file(path) else FindingOrigin.AUTHORED
    relative = _relative(path, root)
    entity = _UNDECLARED_ENTITY
    findings: list[ArtifactFinding] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        declaration = _FSH_DECLARATION.match(line)
        if declaration is not None:
            entity = declaration.group("name")
            continue
        hostile = _hostile_fsh_string(line)
        if hostile is None:
            continue
        findings.append(
            ArtifactFinding(
                file=relative,
                resource_id=entity,
                field=hostile.field,
                value=hostile.value,
                kind=hostile.kind,
                origin=origin,
                message=_message(hostile.kind),
            )
        )
    return findings


def _hostile_fsh_string(line: str) -> _HostileString | None:
    """The build-aborting string one FSH line carries, or None for a line carrying none.

    Three rule shapes reach a published page: the `Title:` keyword, an assignment to one of the
    checked elements, and a concept rule's display. Everything else in a FSH file is structure.
    """
    title = _FSH_TITLE.match(line)
    if title is not None:
        value = title.group("value")
        return _HostileString(field=_FSH_TITLE_FIELD, value=value, kind="name") if build_aborting_name(value) else None
    assignment = _FSH_ASSIGNMENT.match(line)
    if assignment is not None:
        return _hostile_fsh_assignment(assignment.group("path").strip(), assignment.group("value"))
    concept = _FSH_CONCEPT.match(line)
    if concept is not None and build_aborting_name(concept.group("display")):
        return _HostileString(field=f"#{concept.group('code')} display", value=concept.group("display"), kind="name")
    return None


def _hostile_fsh_assignment(path: str, value: str) -> _HostileString | None:
    """The build-aborting string one FSH assignment carries, read off the element its path ends at."""
    element = _fsh_element(path)
    if element in _NAME_ELEMENTS and build_aborting_name(value):
        return _HostileString(field=path, value=value, kind="name")
    if element == _VALUE_ELEMENT and _FSH_IDENTIFIER_SEGMENT in path and build_aborting_code(value):
        return _HostileString(field=path, value=value, kind="code")
    return None


def _fsh_element(path: str) -> str:
    """The element one FSH path ends at, with the slice, index, and caret notation taken off it."""
    return path.rsplit(".", 1)[-1].split("[", 1)[0].lstrip("^").strip()


def _message(kind: Literal["name", "code"]) -> str:
    """Why the IG publisher aborts on one kind of string, in the words the emit-site refusal uses."""
    return _NAME_MESSAGE if kind == "name" else _CODE_MESSAGE


#: Why the guide's own identity aborts the publisher, and why no other file on disk says so first.
_IG_IDENTITY_MESSAGE = (
    "the guide's identity is written into the ImplementationGuide resource and every page rendered "
    "from it, so a '<' in it aborts `make build` in its last pass - and until SUSHI has run, this is "
    "the only place on disk carrying it."
)

#: The `[ig]` keys of fhir.toml whose value the publisher writes into a page, in the file's own order.
#: `id`, `canonical` and `status` are not among them: each is a constrained token no '<' survives.
_IG_CONFIG_KEYS = ("name", "title", "publisher")


class _SushiIdentityLine(BaseModel):
    """One identity value sushi-config states to the IG publisher, and where the file states it."""

    model_config = ConfigDict(frozen=True)

    field: str
    """The YAML element, as a reader of the file would name it."""

    ig_key: str | None
    """The `[ig]` key of fhir.toml the value is written from, where one spells it directly."""

    pattern: str
    """The line the value sits on, matched rather than parsed - the scaffold writes each as one scalar."""


#: Every identity line of sushi-config the publisher carries into a page. `name` is matched at column
#: 0 and the publisher's name at two spaces, so neither takes the other's line. The file is read here
#: rather than only through fhir.toml because the publisher reads this file: a sushi-config edited
#: away from the `[ig]` table is what the build would actually die on.
_SUSHI_IDENTITY_LINES: tuple[_SushiIdentityLine, ...] = (
    _SushiIdentityLine(field="name", ig_key="name", pattern=r"(?m)^name:(?P<value>.*)$"),
    _SushiIdentityLine(field="title", ig_key="title", pattern=r"(?m)^title:(?P<value>.*)$"),
    _SushiIdentityLine(field="description", ig_key=None, pattern=r"(?m)^description:(?P<value>.*)$"),
    _SushiIdentityLine(field="publisher.name", ig_key="publisher", pattern=r"(?m)^  name:(?P<value>.*)$"),
)


def _ig_identity_findings(project: FhirProject) -> list[ArtifactFinding]:
    """Every build-aborting string in the guide's own identity, named at the file that states it.

    `fhir.toml` is read first because it is the source: `d2w fhir init --refresh` writes every other
    file's copy from it, so the `[ig]` table is where the value is changed. `ig/sushi-config.yaml` is
    read after it, for what fhir.toml does not spell - the description the scaffold derives from the
    title - and for a file edited away from the table it was written from. A value already named at
    its source is not named twice.
    """
    ig = project.config.ig
    findings = [
        ArtifactFinding(
            file=FHIR_CONFIG_FILENAME,
            resource_id=ig.id,
            field=f"ig.{key}",
            value=value,
            kind="name",
            origin=FindingOrigin.IG_IDENTITY,
            ig_key=key,
            message=_IG_IDENTITY_MESSAGE,
        )
        for key, value in ((key, str(getattr(ig, key))) for key in _IG_CONFIG_KEYS)
        if build_aborting_name(value)
    ]
    published = _read_text(project.project_root / SUSHI_CONFIG_RELATIVE_PATH)
    if published is None:
        return findings
    stated = {finding.value for finding in findings}
    for line in _SUSHI_IDENTITY_LINES:
        match = re.search(line.pattern, published)
        if match is None:
            continue
        value = match.group("value").strip()
        if not build_aborting_name(value) or value in stated:
            continue
        findings.append(
            ArtifactFinding(
                file=SUSHI_CONFIG_RELATIVE_PATH,
                resource_id=ig.id,
                field=line.field,
                value=value,
                kind="name",
                origin=FindingOrigin.IG_IDENTITY,
                ig_key=line.ig_key,
                message=_IG_IDENTITY_MESSAGE,
            )
        )
    return findings


#: Why a form whose assignment names nothing is worth stopping for, and why it stops nothing itself.
_EMPTY_ASSIGNMENT_MESSAGE = (
    "the form's organisation-unit assignment List names no organisation unit this project publishes, "
    "so no organisation unit may report it and the facade refuses to draft a response for it. The "
    "guide builds and publishes either way, which is why this is a warning: what it costs is a form, "
    "not a build."
)

#: The element an assignment List carries its members on. A List with none is one no organisation unit is on.
_LIST_ENTRY_ELEMENT = "entry"

#: One FSH `Reference(<target>)`, which is how a generated Questionnaire names its assignment List.
_FSH_REFERENCE = re.compile(r"Reference\((?P<target>[^)\s]+)\)")


def _empty_assignment_findings(project: FhirProject, root: Path) -> list[ArtifactFinding]:
    """Every published form referencing an organisation-unit assignment List that names no organisation unit.

    Counted in forms rather than in the data sets and programs DHIS2 hangs the assignment on: a
    tracker program's stages each publish a Questionnaire of their own and share the one List, and
    the form is what a capture client is refused at. It is the same unit `d2w fhir generate` reports
    and the same unit the facade counts when it answers `$generate` with a 422.
    """
    empty = _empty_assignment_list_ids(project)
    if not empty:
        return []
    references = {f"{ASSIGNMENT_LIST_RESOURCE_TYPE}/{list_id}" for list_id in sorted(empty)}
    findings: list[ArtifactFinding] = []
    for path in _json_paths(project):
        document = _read_document(path)
        if not isinstance(document, dict) or not isinstance(document.get(_RESOURCE_TYPE_ELEMENT), str):
            continue
        resource_id = document.get("id")
        named = resource_id if isinstance(resource_id, str) else _UNIDENTIFIED_RESOURCE
        findings.extend(
            _empty_assignment_finding(_relative(path, root), named, field, value)
            for field, value in _strings(document, prefix="")
            if value in references
        )
    for path in _fsh_paths(project):
        text = _read_text(path)
        if text is None:
            continue
        findings.extend(
            _empty_assignment_finding(_relative(path, root), path.stem, f"line {number}", match.group("target"))
            for number, line in enumerate(text.splitlines(), start=1)
            for match in _FSH_REFERENCE.finditer(line)
            if match.group("target") in references
        )
    return findings


def _empty_assignment_finding(file: str, resource_id: str, field: str, value: str) -> ArtifactFinding:
    """One form named at the reference by which it names an assignment List no organisation unit is on."""
    return ArtifactFinding(
        file=file,
        resource_id=resource_id,
        field=field,
        value=value,
        kind="assignment",
        origin=FindingOrigin.ASSIGNMENT,
        message=_EMPTY_ASSIGNMENT_MESSAGE,
    )


def _empty_assignment_list_ids(project: FhirProject) -> set[str]:
    """The ids of the assignment Lists on disk that carry no entry at all.

    The Lists are pre-built JSON the compile step passes through untouched, so they read the same
    before and after SUSHI has run - which is what lets this answer on a project that has only
    generated.
    """
    directory = project.resources_directory / ASSIGNMENT_DIRECTORY
    if not directory.is_dir():
        return set()
    ids: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        document = _read_document(path)
        if not isinstance(document, dict) or document.get(_RESOURCE_TYPE_ELEMENT) != ASSIGNMENT_LIST_RESOURCE_TYPE:
            continue
        list_id = document.get("id")
        if isinstance(list_id, str) and not document.get(_LIST_ENTRY_ELEMENT):
            ids.add(list_id)
    return ids


#: Why a form whose every combo is restricted away is worth stopping for, and why it stops nothing itself.
_UNUSABLE_ATTRIBUTE_OPTION_COMBO_MESSAGE = (
    "DHIS2 restricts every attribute option combo of the vocabulary this form binds away from every "
    "organisation unit this project publishes, so no capture for the form can be keyed to a combo this "
    "DHIS2 instance accepts and it is refused with E8025 whichever one it names. The guide builds and "
    "publishes either way, which is why this is a warning: what it costs is a form, not a build."
)

#: Why a form whose every combo has closed is worth stopping for, and why it stops nothing itself.
_UNTIMELY_ATTRIBUTE_OPTION_COMBO_MESSAGE = (
    "DHIS2 has closed every attribute option combo of the vocabulary this form binds: no attribute option "
    "combo of the form is valid for any period it reports, so no capture for the form can be keyed to a combo "
    "this DHIS2 instance accepts and it is refused with E8032 whichever one it names. The guide builds and "
    "publishes either way, which is why this is a warning: what it costs is a form, not a build."
)

#: The element a CodeSystem carries its concepts on, and the one a concept carries its properties on.
_CONCEPT_ELEMENT = "concept"
_PROPERTY_ELEMENT = "property"

#: The element a resource carries its extensions on, which is where a Questionnaire states its period type.
_EXTENSION_ELEMENT = "extension"

#: How many leading characters of an R4 `dateTime` spell the calendar day DHIS2 scopes a category option by.
_ISO_DATE_LENGTH = 10

#: One FSH `Canonical(<target>)`, which is how a generated Questionnaire binds its combo vocabulary.
_FSH_CANONICAL = re.compile(r"Canonical\((?P<target>[^)\s]+)\)")

#: The two facts an FSH Questionnaire states about the period it reports for and the vocabulary it keys by.
_FSH_PERIOD_TYPE = re.compile(r"^\* extension\[D2PeriodType\]\.valueCode = #(?P<period_type>\S+)$", re.MULTILINE)
_FSH_ATTRIBUTE_OPTION_COMBOS = re.compile(
    r"^\* extension\[D2AttributeOptionCombos\]\.valueCanonical = Canonical\((?P<value_set>[^)\s]+)\)$",
    re.MULTILINE,
)


def _unusable_attribute_option_combo_findings(project: FhirProject, root: Path) -> list[ArtifactFinding]:
    """Every published form binding an attribute-combo vocabulary no published organisation unit may draw from.

    The same fact `d2w fhir generate` closes its run with, read back off the files that run wrote
    rather than off the instance - which is what lets a build machine with no DHIS2 connection ask
    it. A combo concept names one restriction List per restricted category option it is met from, and
    a capture may be keyed to that concept only at an organisation unit every one of those Lists
    holds; a vocabulary whose every concept leaves that intersection empty is one nobody may file
    under, and the forms binding it are forms nobody may submit.

    Counted at the reference, the way the empty-assignment finding is: one row per file and element
    naming the vocabulary, so the row a reader opens is the form rather than the terminology.
    """
    directory = project.resources_directory / ATTRIBUTE_COMBO_DIRECTORY
    if not directory.is_dir():
        return []
    documents = [document for path in sorted(directory.glob("*.json")) if (document := _read_document(path))]
    restrictions = _restriction_members(documents)
    unusable_systems = {
        url
        for document in documents
        if isinstance(document, dict)
        and document.get(_RESOURCE_TYPE_ELEMENT) == "CodeSystem"
        and isinstance(url := document.get("url"), str)
        and _every_concept_is_unusable(document, restrictions)
    }
    if not unusable_systems:
        return []
    named = _vocabulary_names(documents, unusable_systems)
    if not named:
        return []
    findings: list[ArtifactFinding] = []
    for path in _json_paths(project):
        # The vocabulary's own files state their own name and canonical; a resource does not bind itself.
        if path.parent == directory:
            continue
        document = _read_document(path)
        if not isinstance(document, dict) or not isinstance(document.get(_RESOURCE_TYPE_ELEMENT), str):
            continue
        resource_id = document.get("id")
        found = resource_id if isinstance(resource_id, str) else _UNIDENTIFIED_RESOURCE
        findings.extend(
            _unusable_attribute_option_combo_finding(_relative(path, root), found, field, value)
            for field, value in _strings(document, prefix="")
            if value in named
        )
    for path in _fsh_paths(project):
        text = _read_text(path)
        if text is None:
            continue
        findings.extend(
            _unusable_attribute_option_combo_finding(
                _relative(path, root), path.stem, f"line {number}", match.group("target")
            )
            for number, line in enumerate(text.splitlines(), start=1)
            for match in _FSH_CANONICAL.finditer(line)
            if match.group("target") in named
        )
    return findings


def _unusable_attribute_option_combo_finding(file: str, resource_id: str, field: str, value: str) -> ArtifactFinding:
    """One form named at the reference by which it binds a combo vocabulary no organisation unit may draw from."""
    return ArtifactFinding(
        file=file,
        resource_id=resource_id,
        field=field,
        value=value,
        kind="attribute-option-combo",
        origin=FindingOrigin.ATTRIBUTE_OPTION_COMBO,
        message=_UNUSABLE_ATTRIBUTE_OPTION_COMBO_MESSAGE,
    )


def _untimely_attribute_option_combo_findings(project: FhirProject, root: Path, today: date) -> list[ArtifactFinding]:
    """Every published form binding an attribute-combo vocabulary DHIS2 has closed for every period it reports.

    The date axis's answer to `_unusable_attribute_option_combo_findings`, and the same fact
    `d2w fhir generate` closes its run with, read back off the files that run wrote rather than off
    the instance. Every fact it needs is on disk: a combo concept publishes the window its category
    options are open for as `dhis2-valid-from` / `dhis2-valid-to`, and the form publishes the DHIS2
    period type it reports on, so a build machine with no connection can ask the question.

    "Any period it reports" is read forward from the period the form reports now - the newest
    completed period of its own period type, which is the period `$generate` drafts a capture for. A
    window that closed before that period ends closed before every later period's end too, so a
    vocabulary whose every concept has closed for this one has closed for every period the form
    still reports, and the forms binding it are forms nobody may submit.

    Counted at the reference, the way the unit-axis finding is: one row per form and element naming
    the vocabulary, because the period type is the form's own and two forms binding one vocabulary
    can report on different ones.
    """
    directory = project.resources_directory / ATTRIBUTE_COMBO_DIRECTORY
    if not directory.is_dir():
        return []
    documents = [document for path in sorted(directory.glob("*.json")) if (document := _read_document(path))]
    windows = _vocabulary_windows(documents)
    if not windows:
        return []
    findings: list[ArtifactFinding] = []
    for path in _json_paths(project):
        # The vocabulary's own files state their own name and canonical; a resource does not bind itself.
        if path.parent == directory:
            continue
        document = _read_document(path)
        if not isinstance(document, dict) or document.get(_RESOURCE_TYPE_ELEMENT) != "Questionnaire":
            continue
        resource_id = document.get("id")
        found = resource_id if isinstance(resource_id, str) else _UNIDENTIFIED_RESOURCE
        period_type = _json_period_type(document)
        findings.extend(
            _untimely_attribute_option_combo_finding(_relative(path, root), found, field, value)
            for field, value in _strings(document, prefix="")
            if _vocabulary_has_closed(windows.get(value), period_type, today)
        )
    for path in _fsh_paths(project):
        text = _read_text(path)
        if text is None:
            continue
        period_match = _FSH_PERIOD_TYPE.search(text)
        period_type = period_match.group("period_type") if period_match is not None else None
        findings.extend(
            _untimely_attribute_option_combo_finding(
                _relative(path, root), path.stem, f"line {number}", match.group("value_set")
            )
            for number, line in enumerate(text.splitlines(), start=1)
            for match in _FSH_ATTRIBUTE_OPTION_COMBOS.finditer(line)
            if _vocabulary_has_closed(windows.get(match.group("value_set")), period_type, today)
        )
    return findings


def _untimely_attribute_option_combo_finding(file: str, resource_id: str, field: str, value: str) -> ArtifactFinding:
    """One form named at the reference by which it binds a combo vocabulary DHIS2 has closed."""
    return ArtifactFinding(
        file=file,
        resource_id=resource_id,
        field=field,
        value=value,
        kind="attribute-option-combo",
        origin=FindingOrigin.UNTIMELY_ATTRIBUTE_OPTION_COMBO,
        message=_UNTIMELY_ATTRIBUTE_OPTION_COMBO_MESSAGE,
    )


def _vocabulary_has_closed(
    concept_windows: tuple[CategoryOptionValidity, ...] | None, period_type: str | None, today: date
) -> bool:
    """Whether every concept of one bound vocabulary closed before the period a form of this type reports now."""
    if not concept_windows or period_type is None:
        return False
    period = _current_period(period_type, today)
    if period is None:
        return False
    return all(window.closed_before(period.end_date) for window in concept_windows)


def _current_period(period_type: str, today: date) -> PeriodValue | None:
    """The newest completed period of one DHIS2 period type, which is the period a form reports now."""
    isos = recent_periods(period_type, 1, today)
    return parse_period(isos[0]) if isos else None


def _vocabulary_windows(documents: list[Any]) -> dict[str, tuple[CategoryOptionValidity, ...]]:
    """The window every concept of each combo vocabulary is open for, by the spellings a form binds it under."""
    by_system = _concept_windows(documents)
    if not by_system:
        return {}
    named: dict[str, tuple[CategoryOptionValidity, ...]] = {}
    for document in documents:
        if not isinstance(document, dict) or document.get(_RESOURCE_TYPE_ELEMENT) != "ValueSet":
            continue
        systems = sorted(_included_systems(document.get("compose")) & set(by_system))
        if not systems:
            continue
        concept_windows = tuple(window for system in systems for window in by_system[system])
        for key in ("url", "name"):
            if isinstance(value := document.get(key), str):
                named[value] = concept_windows
    return named


def _concept_windows(documents: list[Any]) -> dict[str, tuple[CategoryOptionValidity, ...]]:
    """The window every concept of each combo CodeSystem is open for, by the CodeSystem's own canonical."""
    windows: dict[str, tuple[CategoryOptionValidity, ...]] = {}
    for document in documents:
        if not isinstance(document, dict) or document.get(_RESOURCE_TYPE_ELEMENT) != "CodeSystem":
            continue
        concepts = document.get(_CONCEPT_ELEMENT)
        if not isinstance(url := document.get("url"), str) or not isinstance(concepts, list) or not concepts:
            continue
        windows[url] = tuple(_concept_window(concept) for concept in concepts)
    return windows


def _concept_window(concept: Any) -> CategoryOptionValidity:  # noqa: ANN401 - JSON is Any
    """The calendar window one combo concept publishes, either end of it absent where it states none."""
    return CategoryOptionValidity(
        valid_from=_concept_date(concept, ATTRIBUTE_OPTION_VALID_FROM_PROPERTY),
        valid_to=_concept_date(concept, ATTRIBUTE_OPTION_VALID_TO_PROPERTY),
    )


def _concept_date(concept: Any, property_code: str) -> date | None:  # noqa: ANN401 - JSON is Any
    """One calendar day a concept property states, or None where it states none this scan can read.

    An R4 `dateTime` admits more than a day - a time, an offset - and DHIS2 scopes a category option
    by calendar day, so the day is what is read and anything beyond it is passed over.
    """
    properties = concept.get(_PROPERTY_ELEMENT) if isinstance(concept, dict) else None
    for entry in properties if isinstance(properties, list) else ():
        if not isinstance(entry, dict) or entry.get("code") != property_code:
            continue
        if not isinstance(value := entry.get("valueDateTime"), str):
            continue
        try:
            return date.fromisoformat(value[:_ISO_DATE_LENGTH])
        except ValueError:
            return None
    return None


def _json_period_type(document: dict[str, Any]) -> str | None:
    """The DHIS2 period type one compiled Questionnaire declares, read the way `$generate` reads it.

    The declaration is an extension carrying a `valueCode`, and a code this toolchain's own period-type
    vocabulary does not name is read as no declaration: the form would be stating a type no DHIS2
    period can be spelled in, exactly as the capture facade decides it.
    """
    extensions = document.get(_EXTENSION_ELEMENT)
    for entry in extensions if isinstance(extensions, list) else ():
        if isinstance(entry, dict) and (code := entry.get("valueCode")) in PERIOD_TYPE_NAMES:
            return str(code)
    return None


def _restriction_members(documents: list[Any]) -> dict[str, frozenset[str]]:
    """The organisation units each restriction List admits, keyed by the reference a concept names it by."""
    members: dict[str, frozenset[str]] = {}
    for document in documents:
        if not isinstance(document, dict) or document.get(_RESOURCE_TYPE_ELEMENT) != "List":
            continue
        list_id = document.get("id")
        if not isinstance(list_id, str):
            continue
        entries = document.get(_LIST_ENTRY_ELEMENT)
        reference = f"{ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE}/{list_id}"
        members[reference] = frozenset(_list_entry_references(entries))
    return members


def _list_entry_references(entries: Any) -> Iterator[str]:  # noqa: ANN401 - JSON is Any
    """Yield the reference each entry of one List names, passing over an entry shaped any other way."""
    for entry in entries if isinstance(entries, list) else ():
        if not isinstance(entry, dict):
            continue
        item = entry.get("item")
        if isinstance(item, dict) and isinstance(reference := item.get("reference"), str):
            yield reference


def _every_concept_is_unusable(document: dict[str, Any], restrictions: dict[str, frozenset[str]]) -> bool:
    """Whether no concept of one combo CodeSystem may be filed at any organisation unit the project publishes."""
    concepts = document.get(_CONCEPT_ELEMENT)
    if not isinstance(concepts, list) or not concepts:
        return False
    return all(_concept_admits_nothing(concept, restrictions) for concept in concepts)


def _concept_admits_nothing(concept: Any, restrictions: dict[str, frozenset[str]]) -> bool:  # noqa: ANN401 - JSON
    """Whether the restriction Lists one combo concept names leave no organisation unit admitting it.

    A concept naming no restriction is admitted everywhere, and one naming a List this scan did not
    read is not judged at all: the answer has to be read off files that are there, and a missing
    List is a tree nothing generated rather than a combo nobody may file under.
    """
    if not isinstance(concept, dict):
        return False
    named = list(_restriction_references(concept.get(_PROPERTY_ELEMENT)))
    if not named or any(reference not in restrictions for reference in named):
        return False
    admitted = frozenset[str].intersection(*(restrictions[reference] for reference in named))
    return not admitted


def _restriction_references(properties: Any) -> Iterator[str]:  # noqa: ANN401 - JSON is Any
    """Yield every restriction List one combo concept names, one per restricted category option it is met from."""
    for entry in properties if isinstance(properties, list) else ():
        if not isinstance(entry, dict) or entry.get("code") != ATTRIBUTE_OPTION_RESTRICTION_PROPERTY:
            continue
        if isinstance(value := entry.get("valueString"), str):
            yield value


def _vocabulary_names(documents: list[Any], unusable_systems: set[str]) -> set[str]:
    """Every spelling a form binds one of these dead vocabularies by: the ValueSet canonical, and its FSH name."""
    named: set[str] = set()
    for document in documents:
        if not isinstance(document, dict) or document.get(_RESOURCE_TYPE_ELEMENT) != "ValueSet":
            continue
        if not _included_systems(document.get("compose")) & unusable_systems:
            continue
        named.update(value for key in ("url", "name") if isinstance(value := document.get(key), str))
    return named


def _included_systems(compose: Any) -> set[str]:  # noqa: ANN401 - JSON is Any
    """The CodeSystem urls one ValueSet composes itself from."""
    includes = compose.get("include") if isinstance(compose, dict) else None
    entries = includes if isinstance(includes, list) else []
    return {system for entry in entries if isinstance(entry, dict) and isinstance(system := entry.get("system"), str)}


def _read_text(path: Path) -> str | None:
    """Read one file as text, treating an absent or undecodable file as nothing to scan."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


#: Why a selection entry naming nothing is worth stopping for, and why it stops nothing itself.
_SELECTION_MESSAGE = (
    "this project publishes nothing carrying that UID, so the entry selected no DHIS2 object: the "
    "object is not on the instance the guide was generated against, under that id. What it costs is "
    "the form, its examples and its page - the guide builds and publishes without them, which is why "
    "this is a warning rather than a build abort."
)

#: The directory the foundation target writes into. It is written by every generate run whatever the
#: selection holds, so its absence is a project nothing has generated yet - where a selection naming
#: nothing published says only that, and not that the UID is wrong.
_FOUNDATION_DIRECTORY = "foundation"


def _selection_findings(project: FhirProject) -> list[ArtifactFinding]:
    """Every `[generate.*] include_ids` entry the published tree carries no trace of.

    A selected form writes its DHIS2 UID into what it publishes - a data set and an event program
    carry it as their Questionnaire's identifier, a tracker program as the program its stages and
    its assignment List name, a tracked entity type as its own registration form - so a UID absent
    from every published file is a UID nothing was published for. Read off the tree rather than the
    instance, which is what lets this answer with no connection, exactly as the rest of the scan does.

    A table switched off selects nothing by design and is not read, and a project that has never
    generated raises nothing at all: there the tree is empty for a reason that has nothing to do
    with the selection.
    """
    if not (project.fsh_directory / _FOUNDATION_DIRECTORY).is_dir():
        return []
    generate = project.config.generate
    tables = (
        ("data_sets", generate.data_sets),
        ("event_programs", generate.event_programs),
        ("tracker_programs", generate.tracker_programs),
        ("tracked_entity_forms", generate.tracked_entity_forms),
    )
    wanted = {uid for _, table in tables if table.enabled for uid in table.include_ids}
    if not wanted:
        return []
    published = _published_uids(project, wanted)
    return [
        ArtifactFinding(
            file=FHIR_CONFIG_FILENAME,
            resource_id=f"generate.{name}",
            field="include_ids",
            value=uid,
            kind="selection",
            origin=FindingOrigin.SELECTION,
            message=_SELECTION_MESSAGE,
        )
        for name, table in tables
        if table.enabled
        for uid in sorted(set(table.include_ids) - published)
    ]


def _published_uids(project: FhirProject, wanted: set[str]) -> set[str]:
    """Which of the wanted UIDs the published tree names anywhere, reading no more files than it must."""
    found: set[str] = set()
    for path in (*_fsh_paths(project), *_json_paths(project)):
        text = _read_text(path)
        if text is None:
            continue
        found |= {uid for uid in wanted - found if uid in text}
        if found == wanted:
            break
    return found


#: Why a reference into the registry package the guide does not publish stops a build.
_REGISTRY_MESSAGE = (
    "the guide references an organisation unit the registry package it depends on does not publish, "
    "and the IG publisher cannot resolve it"
)


def _registry_findings(project: FhirProject, root: Path, package: Path | None) -> list[ArtifactFinding]:
    """Every reference into the registry package that the package does not publish a resource for.

    Offline, like the rest of the scan: the references are already on disk, in the examples, the
    assignment Lists and the pages the guide wrote, and the registry supplies the ids it publishes.
    A guide publishing its own registry has no such reference and nothing to compare.

    A guide whose registry cannot be read at all is one finding rather than a silent pass, because
    a build against an uninstalled package fails on every reference at once.
    """
    registry = project.config.registry_dependency
    if registry is None:
        return []
    try:
        published = {
            document.body["id"]
            for document in load_registry_documents(project, package=package)
            if document.body.get("resourceType") == "Location" and isinstance(document.body.get("id"), str)
        }
    except RegistryMissingError as error:
        return [
            ArtifactFinding(
                file=FHIR_CONFIG_FILENAME,
                resource_id=registry.id,
                field="generate.organisation_units.registry",
                value=registry.canonical,
                kind="registry",
                origin=FindingOrigin.REGISTRY_MISSING,
                message=str(error),
            )
        ]
    prefix = f"{registry.canonical}/Location/"
    findings = [
        ArtifactFinding(
            file=reference.file,
            resource_id=reference.resource_id,
            field=reference.field,
            value=reference.value,
            kind="registry",
            origin=FindingOrigin.REGISTRY_SELECTION,
            message=_REGISTRY_MESSAGE,
        )
        for reference in _registry_references(project, root, prefix)
        if reference.value.removeprefix(prefix).split("/", 1)[0] not in published
    ]
    return findings


class _RegistryReference(BaseModel):
    """One reference into the registry package, and where on disk the guide states it."""

    model_config = ConfigDict(frozen=True)

    file: str
    resource_id: str
    field: str
    value: str


def _registry_references(project: FhirProject, root: Path, prefix: str) -> list[_RegistryReference]:
    """Every `<registry canonical>/Location/<id>` the guide states, in JSON and in FSH alike."""
    references: list[_RegistryReference] = []
    for path in _json_paths(project):
        document = _read_document(path)
        if not isinstance(document, dict) or not isinstance(document.get(_RESOURCE_TYPE_ELEMENT), str):
            continue
        resource_id = document.get("id")
        named = resource_id if isinstance(resource_id, str) else _UNIDENTIFIED_RESOURCE
        references.extend(
            _RegistryReference(file=_relative(path, root), resource_id=named, field=field, value=value)
            for field, value in _strings(document, prefix="")
            if value.startswith(prefix)
        )
    for path in _fsh_paths(project):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        references.extend(
            _RegistryReference(file=_relative(path, root), resource_id=path.stem, field=f"line {number}", value=value)
            for number, line in enumerate(lines, start=1)
            for value in _FSH_REGISTRY_REFERENCE.findall(line)
            if value.startswith(prefix)
        )
    return references


#: A `Reference(<url>)` as FSH writes one, which is how every generated reference into the registry reads.
_FSH_REGISTRY_REFERENCE = re.compile(r"Reference\((https?://[^)\s]+)\)")


def _strings(node: Any, *, prefix: str) -> Iterator[tuple[str, str]]:  # noqa: ANN401 - JSON is Any
    """Yield every string under one JSON node with the element path down to it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, prefix=f"{prefix}.{key}" if prefix else str(key))
        return
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from _strings(item, prefix=f"{prefix}[{index}]")
        return
    if isinstance(node, str):
        yield prefix, node


def _relative(path: Path, root: Path) -> str:
    """One scanned file named the way a reader would type it: relative to the project root."""
    return path.relative_to(root).as_posix()
