"""Scaffold schemas: the `d2w fhir init` inputs and the files it writes."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dhis2w_fhir.names import strip_trailing_slash
from dhis2w_fhir.resources.organisation_units.schemas import RegistryDependency
from dhis2w_fhir.status import ORGANISATION_UNIT_PACKAGE, IgStatus, PackageContent, ProjectKind

_NON_PROJECT_NAME_CHARACTERS = re.compile(r"[^a-z0-9]+")

#: Seconds the IG publisher gives its internal SUSHI run, written to `[FSH] timeout` of `ig/fsh.ini`.
#: The publisher's own default is 300, which any IG built from a real DHIS2 instance overruns.
DEFAULT_SUSHI_TIMEOUT_SECONDS = 1800


def normalize_project_name(ig_id: str) -> str:
    """Normalise an IG id into a PEP 508 project name (`dhis2.fhir.sldemo` -> `dhis2-fhir-sldemo`)."""
    return _NON_PROJECT_NAME_CHARACTERS.sub("-", ig_id.lower()).strip("-")


class InitOptions(BaseModel):
    """Parameters for `d2w fhir init` scaffolding.

    `profile` seeds the top-level `profile` key, and `data_set_ids` / `event_program_ids` /
    `tracker_program_ids` seed the `[generate.data_sets]`, `[generate.event_programs]`, and
    `[generate.tracker_programs]` include lists of the scaffolded `fhir.toml`. Scaffolding is
    offline: the profile name and the UIDs are written as given and
    never resolved or checked against an instance. `sushi_timeout` is the `[FSH] timeout` of
    `ig/fsh.ini`, the ceiling the IG publisher gives its internal SUSHI run. `max_level` caps the
    organisation-unit registry, the usual reason an IG is too large to compile inside that ceiling.
    `identifier_system_base` is the stem the six `special-url` lines of `ig/sushi-config.yaml`
    carry, and matches the default of `GenerateConfig.identifier_system_base` that a scaffolded
    `fhir.toml` leaves unwritten.

    `kind` is what the project publishes: a guide, or a registry package holding the
    organisation-unit registry alone. `registry` is the registry package a guide depends on -
    the `[generate.organisation_units.registry]` table it seeds, the `dependencies:` entry of
    `ig/sushi-config.yaml`, and the `REGISTRY_*` knobs of the Makefile. A registry package
    depends on no registry.
    """

    ig_id: str
    canonical: str
    name: str
    title: str
    publisher: str
    status: IgStatus = "draft"
    publisher_url: str | None = None
    profile: str | None = None
    sushi_timeout: int = DEFAULT_SUSHI_TIMEOUT_SECONDS
    identifier_system_base: str = "http://dhis2.org/fhir"
    max_level: int | None = None
    data_set_ids: list[str] = Field(default_factory=list)
    event_program_ids: list[str] = Field(default_factory=list)
    tracker_program_ids: list[str] = Field(default_factory=list)
    kind: ProjectKind = "guide"
    publishes: PackageContent | None = None

    registry: RegistryDependency | None = None

    _normalize_canonical = field_validator("canonical")(strip_trailing_slash)

    @model_validator(mode="after")
    def _package_stands_alone(self) -> InitOptions:
        """A package says what it holds, publishes that alone, and depends on no package of its own."""
        if self.kind == "guide":
            if self.publishes is not None:
                raise ValueError("`publishes` is what a package holds; a guide states none")
            return self
        if self.publishes is None:
            raise ValueError('a package needs `publishes` to say what it holds (e.g. "organisation-units")')
        if self.publishes == ORGANISATION_UNIT_PACKAGE:
            if self.registry is not None:
                raise ValueError("a registry package publishes the registry itself and depends on none")
            if self.data_set_ids or self.event_program_ids or self.tracker_program_ids:
                raise ValueError("a registry package publishes the organisation-unit registry alone and no form")
        return self


class ScaffoldFile(BaseModel):
    """One file emitted by `d2w fhir init`: path relative to the project root plus its content.

    `from_template` separates the thirteen files the scaffold renders from the hundreds a template
    payload lays down beside them. Only the former are identity-rendered, and only the former are
    what `d2w fhir init --refresh` maintains.
    """

    model_config = ConfigDict(frozen=True)

    relative_path: str
    content: str
    from_template: bool = False


class ProjectScaffoldState(BaseModel):
    """The scaffold inputs of an existing project, recovered from the project's own files.

    `d2w fhir init --refresh` compares against the scaffold *this* project would produce, so the
    inputs come off disk: the IG identity from the `[ig]` table of `fhir.toml`, the SUSHI timeout
    from `ig/fsh.ini`, and the publisher URL plus `copyright_year` from `ig/sushi-config.yaml` -
    the two values no other file in the project records.
    """

    model_config = ConfigDict(frozen=True)

    options: InitOptions
    copyright_year: int


class ScaffoldReport(BaseModel):
    """Outcome of `d2w fhir init`.

    Scaffolding a project reports through `created_files` (written where nothing stood),
    `overwritten_files` (a file that already stood there, replaced under `--force`, whatever it
    held), and `skipped_files` (left alone because the file exists). Created and overwritten are
    counted apart because they are different acts: one composes a project, the other discards one.

    A refresh reports through `created_files` (a scaffold file the project lacks),
    `rewritten_files` (one of the five toolchain files the scaffold owns outright, replaced whole
    from the current render), `refreshed_files` (rewritten line-preservingly, so every line on disk
    is still there), `unchanged_files` (already current), `extended_files` (carrying every line the
    current scaffold renders plus lines of the user's own, so there is nothing to add), and
    `diverged_files` (holding lines the current scaffold does not write - the user's edits, or
    scaffold lines that have since changed; a line-preserving refresh cannot tell the two apart, so
    it claims neither and the file stays).

    A project scaffolded from a template names it in `template` and reports its payload through
    `template_files`, `overwritten_template_files` and `skipped_template_files`, the same verdicts
    as the scaffold's own files. The payload is hundreds of files wide where the scaffold is
    thirteen, so it is counted apart from `created_files` rather than folded into it: a caller
    reading the report sees which files `d2w fhir init` composed and which tree it laid down
    beside them.

    `notes` carries what a run has to say for itself beyond the per-file verdicts: a file the
    project holds that the scaffold does not write, which a refresh names so the person can
    delete it.
    """

    directory: Path
    template: str | None = None
    created_files: list[str] = Field(default_factory=list)
    overwritten_files: list[str] = Field(default_factory=list)
    skipped_files: list[str] = Field(default_factory=list)
    template_files: list[str] = Field(default_factory=list)
    overwritten_template_files: list[str] = Field(default_factory=list)
    skipped_template_files: list[str] = Field(default_factory=list)
    rewritten_files: list[str] = Field(default_factory=list)
    refreshed_files: list[str] = Field(default_factory=list)
    unchanged_files: list[str] = Field(default_factory=list)
    extended_files: list[str] = Field(default_factory=list)
    diverged_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
