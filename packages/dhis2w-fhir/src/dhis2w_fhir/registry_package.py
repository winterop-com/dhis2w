"""Reading the organisation-unit registry a guide depends on, from a checkout or a built package.

A guide that names `[generate.organisation_units.registry]` publishes no `Organization` and no
`Location` of its own, so the two readers that need them - the facade's resource store and the
translator's compiled artifacts - have to find them in the package instead. Both come through
`load_registry_documents`, so a guide serves and forwards against the very resources the
publisher built its dependency from.

Two sources, tried in that order. `registry.path` is a local checkout of the registry project,
whose `ig/input/resources/registry/` holds the JSON `d2w fhir generate` wrote - the everyday case
while both projects sit side by side, and the one that needs no build at all. A package given on
the command line is the hand-off case: the `package.tgz` the registry's own `make build` wrote, or
a directory it was extracted into. Neither present is a refusal naming both remedies rather than a
guide that silently serves no place.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from dhis2w_core.cli_errors import CliUserError
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from dhis2w_fhir.config import FhirProject
    from dhis2w_fhir.resources.organisation_units.schemas import RegistryDependency

__all__ = [
    "REGISTRY_PACKAGE_RESOURCE_TYPES",
    "RegistryDocument",
    "RegistryMissingError",
    "RegistrySource",
    "load_registry_documents",
    "resolve_registry_source",
]

#: Where a checkout of the registry project keeps the instances `d2w fhir generate` wrote.
_CHECKOUT_REGISTRY_RELATIVE_PATH = Path("ig") / "input" / "resources" / "registry"

#: The directory every FHIR package tarball roots its resources at.
_PACKAGE_ROOT = "package"

#: What a guide reads out of its registry package: the two resources a unit is published as.
#:
#: The package also ships its profiles, its level terminology and its own ImplementationGuide.
#: A guide resolves those by canonical against the published registry rather than serving copies
#: of them, and loading them here would put a second ImplementationGuide in a facade that answers
#: for one guide. So the read is narrowed to the instances, which is what a reference resolves to.
REGISTRY_PACKAGE_RESOURCE_TYPES: frozenset[str] = frozenset({"Location", "Organization"})


class RegistryMissingError(CliUserError):
    """Raised when a guide declares a registry package that neither a checkout nor a package supplies."""


class RegistrySource(BaseModel):
    """Where one run reads the registry from, decided before anything is parsed.

    Resolving is separate from reading so a server can refuse a registry it cannot reach before
    it prints a starting banner, without paying to parse thousands of instances twice.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["checkout", "package"]
    location: Path

    def describe(self) -> str:
        """How the source reads in a diagnostic or a startup line."""
        noun = "checkout" if self.kind == "checkout" else "package"
        return f"{noun} {self.location}"


class RegistryDocument(BaseModel):
    """One resource read out of the registry, with whatever names it in a diagnostic."""

    model_config = ConfigDict(frozen=True)

    source: str
    """Where the resource came from: a file path, or `<archive>:<member>` inside a package."""

    body: dict[str, Any]


def resolve_registry_source(project: FhirProject, *, package: Path | None = None) -> RegistrySource | None:
    """Decide where this run reads the registry from, or refuse; None when the guide publishes it inline.

    The configured checkout is tried first, so two projects side by side keep working off the files
    `d2w fhir generate` wrote and need no build at all. A package named on the command line is the
    hand-off case and answers second. Reaching neither is a refusal naming both remedies.

    Nothing is parsed here - a directory holding at least one resource file, or an archive that
    exists, is enough to say the run can proceed.
    """
    registry = project.config.registry_dependency
    if registry is None:
        return None
    checkout = _checkout_directory(project, registry)
    if checkout is not None:
        return RegistrySource(kind="checkout", location=checkout)
    if package is not None:
        if not package.exists():
            raise RegistryMissingError(f"{package}: no such file or directory")
        return RegistrySource(kind="package", location=package)
    raise RegistryMissingError(_no_source_message(project, registry))


def load_registry_documents(project: FhirProject, *, package: Path | None = None) -> list[RegistryDocument]:
    """Read the organisation-unit resources of the registry package this guide depends on.

    Empty for a guide that publishes its registry inline, which is every guide without the
    `[generate.organisation_units.registry]` table - the caller reads that guide's own
    `ig/input/resources/registry/` as it always has, and nothing here applies.

    `package` is the archive or extracted directory named on the command line, tried after the
    configured checkout so a project that has both keeps working from the sources on disk.
    """
    source = resolve_registry_source(project, package=package)
    if source is None:
        return []
    documents = _source_documents(source)
    if not documents:
        registry = project.config.registry_dependency
        identifier = registry.id if registry is not None else "the registry"
        raise RegistryMissingError(
            f"{source.describe()} holds no organisation-unit resource for {identifier}. A package "
            "built by `make build` in the registry project carries them under `package/`, and a "
            "checkout carries them under `ig/input/resources/registry/` once `d2w fhir generate` "
            "has run there."
        )
    return documents


def _source_documents(source: RegistrySource) -> list[RegistryDocument]:
    """Read every organisation-unit resource the resolved source holds."""
    if source.location.is_dir():
        root = source.location
        if source.kind == "package" and (root / _PACKAGE_ROOT).is_dir():
            root = root / _PACKAGE_ROOT
        return [
            document
            for path in sorted(root.rglob("*.json"))
            if (document := _document(_read_json(path, str(path)), str(path))) is not None
        ]
    return _archive_documents(source.location)


def _checkout_directory(project: FhirProject, registry: RegistryDependency) -> Path | None:
    """The checkout's registry directory when `registry.path` names one holding resources, else None."""
    if registry.path is None:
        return None
    directory = (project.project_root / registry.path / _CHECKOUT_REGISTRY_RELATIVE_PATH).resolve()
    if not directory.is_dir() or not any(directory.rglob("*.json")):
        return None
    return directory


def _archive_documents(package: Path) -> list[RegistryDocument]:
    """Read every organisation-unit resource out of a package tarball, without extracting it to disk."""
    documents: list[RegistryDocument] = []
    try:
        with tarfile.open(package, "r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith(".json"):
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                source = f"{package}:{member.name}"
                document = _document(_parse_json(handle.read().decode("utf-8"), source), source)
                if document is not None:
                    documents.append(document)
    except tarfile.TarError as error:
        raise RegistryMissingError(f"{package}: not a readable package archive ({error})") from error
    return documents


def _document(body: dict[str, Any], source: str) -> RegistryDocument | None:
    """One resource as a document, or None for a resource type a guide does not read out of the registry."""
    if body.get("resourceType") not in REGISTRY_PACKAGE_RESOURCE_TYPES:
        return None
    return RegistryDocument(source=source, body=body)


def _read_json(path: Path, source: str) -> dict[str, Any]:
    """Read one resource file, failing loudly and naming it."""
    return _parse_json(path.read_text(encoding="utf-8"), source)


def _parse_json(text: str, source: str) -> dict[str, Any]:
    """Parse one resource, failing loudly and naming where it came from."""
    try:
        body = json.loads(text)
    except json.JSONDecodeError as error:
        raise RegistryMissingError(f"{source}: not valid JSON ({error})") from error
    if not isinstance(body, dict):
        raise RegistryMissingError(f"{source}: expected a JSON object holding a FHIR resource")
    return body


def _no_source_message(project: FhirProject, registry: RegistryDependency) -> str:
    """The refusal naming both ways to supply the registry, and the one the project already half-states."""
    stated = (
        f"`path` in [generate.organisation_units.registry] names {registry.path}, which holds no "
        f"{_CHECKOUT_REGISTRY_RELATIVE_PATH.as_posix()} - run `d2w fhir generate` there"
        if registry.path is not None
        else "set `path` in [generate.organisation_units.registry] to a checkout of the registry project"
    )
    return (
        f"{project.config.ig.id} depends on the organisation-unit registry package {registry.id} "
        f"{registry.version}, and neither source for it is readable. Either {stated}, or name the "
        "package the registry's `make build` wrote with `--registry-package <package.tgz>`."
    )
