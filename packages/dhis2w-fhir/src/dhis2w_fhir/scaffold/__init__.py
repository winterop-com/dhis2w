"""Scaffold file contents for `d2w fhir init` - a complete dockerized SUSHI IG project."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from dhis2w_fhir.resources.organisation_units.schemas import RegistryDependency
from dhis2w_fhir.scaffold.project_templates import ProjectTemplate, build_template_files, template_selection
from dhis2w_fhir.scaffold.schemas import InitOptions, ScaffoldFile, normalize_project_name
from dhis2w_fhir.status import ORGANISATION_UNIT_PACKAGE

__all__ = [
    "CONFIG_EXAMPLE_RELATIVE_PATH",
    "DOCKERFILE_RELATIVE_PATH",
    "FSH_INI_RELATIVE_PATH",
    "GUIDE_REGISTRY_README_RELATIVE_PATH",
    "IG_INI_RELATIVE_PATH",
    "INDEX_PAGE_RELATIVE_PATH",
    "MAKEFILE_RELATIVE_PATH",
    "OWNED_WHOLE_RELATIVE_PATHS",
    "PYPROJECT_RELATIVE_PATH",
    "PYTHON_VERSION_RELATIVE_PATH",
    "SUSHI_CONFIG_RELATIVE_PATH",
    "GUIDE_RELATIVE_ROOT",
    "REGISTRY_RELATIVE_ROOT",
    "build_guide_and_registry_files",
    "build_scaffold_files",
]

#: The SUSHI project configuration, and the one file recording the publisher URL and the copyright year.
SUSHI_CONFIG_RELATIVE_PATH = "ig/sushi-config.yaml"

#: The IG publisher's FSH settings, and the one file recording the SUSHI timeout.
FSH_INI_RELATIVE_PATH = "ig/fsh.ini"

#: The catalog of every `fhir.toml` option with its default, which opens on the project's own `[ig]` table.
CONFIG_EXAMPLE_RELATIVE_PATH = "fhir.example.toml"

#: The IG publisher's entry point, which names the ImplementationGuide file by the guide's id.
IG_INI_RELATIVE_PATH = "ig/ig.ini"

#: The guide's front page, whose heading is the guide's title.
INDEX_PAGE_RELATIVE_PATH = "ig/input/pagecontent/index.md"

#: The uv project the scaffold is, whose PEP 508 name is normalised from the guide's id.
PYPROJECT_RELATIVE_PATH = "pyproject.toml"

#: The toolchain the project runs, and the docker image the IG publisher runs inside.
MAKEFILE_RELATIVE_PATH = "Makefile"
DOCKERFILE_RELATIVE_PATH = "Dockerfile"

#: The Python the uv project resolves against.
PYTHON_VERSION_RELATIVE_PATH = ".python-version"

#: The files the scaffold owns whole, which `d2w fhir init --refresh` rewrites from the current render.
#:
#: Each is a toolchain file with no reason to be edited: the Makefile states every knob it has as a
#: `?=` default (`D2W`, `TX_SERVER`, `JAVA_HEAP`) taken from the command line or the environment, the
#: Dockerfile and `.python-version` pin the image and the interpreter, and `ig/ig.ini` and
#: `ig/fsh.ini` carry values the project states elsewhere - the guide's id in `fhir.toml`, and the
#: `[FSH] timeout` that `read_project_scaffold_state` recovers off the file and re-renders unchanged.
#: A scaffold revision that replaces a line in one of them lands whole rather than reading as a
#: divergence nobody authored.
#:
#: One name covers a file wherever the scaffold writes it: `Makefile` is the project's own toolchain
#: file and, at the root of a directory scaffolded with `--with-registry`, the file that drives the
#: two projects in order - both state every knob as a `?=` default, so both land whole. The
#: `README.md` that sits beside that second Makefile is prose and is absent from this tuple, so a
#: refresh takes it through the line ladder and keeps whatever the reader added to it.
OWNED_WHOLE_RELATIVE_PATHS: tuple[str, ...] = (
    MAKEFILE_RELATIVE_PATH,
    DOCKERFILE_RELATIVE_PATH,
    PYTHON_VERSION_RELATIVE_PATH,
    IG_INI_RELATIVE_PATH,
    FSH_INI_RELATIVE_PATH,
)

#: The README of a directory scaffolded with `--with-registry`, whose heading is the guide's title.
#:
#: It is the one scaffold file a single project does not have, so the name collides with nothing:
#: `d2w fhir init` on its own writes no README at all.
GUIDE_REGISTRY_README_RELATIVE_PATH = "README.md"

#: Where each project sits when `d2w fhir init --with-registry` scaffolds both under one directory.
#:
#: The guide names the registry by this relative path in two places - `path` in its fhir.toml and
#: `REGISTRY_TGZ` in its Makefile - so the two constants are what keeps those in step with the
#: directories actually written.
GUIDE_RELATIVE_ROOT = "guide"
REGISTRY_RELATIVE_ROOT = "registry"

#: What the guide's `[generate.organisation_units.registry] path` states, from the guide's own root.
_REGISTRY_FROM_GUIDE = Path("..") / REGISTRY_RELATIVE_ROOT

#: The suffix the registry package's id takes from the guide's, so one `--id` decides both.
_REGISTRY_ID_SUFFIX = "registry"

_ENVIRONMENT = Environment(
    loader=PackageLoader("dhis2w_fhir.scaffold", "templates"),
    autoescape=select_autoescape(default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def build_scaffold_files(
    options: InitOptions, *, copyright_year: int | None = None, template: ProjectTemplate | None = None
) -> list[ScaffoldFile]:
    """Build every file `d2w fhir init` writes, path-relative to the project root.

    `copyright_year` dates the sushi-config copyright and defaults to the current year. A refresh
    passes the year already in the project, so the comparison against the file on disk is faithful
    for a project scaffolded in an earlier year.

    `template` pre-populates the project from a guide already generated against a real DHIS2
    instance: its `[generate]` and `[ips]` tables extend the scaffolded `fhir.toml`, and its
    `ig/input/` tree follows, readdressed to this project's canonical. The scaffold's own files are
    rendered first and stay authoritative, so a payload never lands on a file a refresh maintains.
    """
    year = copyright_year if copyright_year is not None else datetime.now(tz=UTC).year
    files = [
        _render("fhir.toml", "fhir.toml.jinja", options, selection=template_selection(template) if template else None),
        _render(CONFIG_EXAMPLE_RELATIVE_PATH, "fhir.example.toml.jinja", options),
        _render(
            SUSHI_CONFIG_RELATIVE_PATH,
            "sushi-config.yaml.jinja",
            options,
            year=year,
            identifier_system_base=options.identifier_system_base,
        ),
        _render(IG_INI_RELATIVE_PATH, "ig.ini.jinja", options),
        _render(FSH_INI_RELATIVE_PATH, "fsh.ini.jinja", options),
        _render("ig/input/fsh/aliases.fsh", "aliases.fsh.jinja", options),
        _render(INDEX_PAGE_RELATIVE_PATH, "index.md.jinja", options),
        _render("ig/input/ignoreWarnings.txt", "ignoreWarnings.txt.jinja", options),
        _render(
            PYPROJECT_RELATIVE_PATH,
            "pyproject.toml.jinja",
            options,
            project_name=normalize_project_name(options.ig_id),
        ),
        _render(PYTHON_VERSION_RELATIVE_PATH, "python-version.jinja", options),
        _render(MAKEFILE_RELATIVE_PATH, "Makefile.jinja", options),
        _render(DOCKERFILE_RELATIVE_PATH, "Dockerfile.jinja", options),
        _render(".gitignore", "gitignore.jinja", options),
    ]
    if template is None:
        return files
    return files + build_template_files(
        template,
        canonical=options.canonical,
        scaffold_managed={scaffold_file.relative_path for scaffold_file in files},
    )


def build_guide_and_registry_files(options: InitOptions, *, copyright_year: int | None = None) -> list[ScaffoldFile]:
    """Build both projects of a split guide under one directory, wired to each other.

    The guide publishes the forms and depends on the registry package for its organisation units.
    Scaffolding them apart means stating four values twice - the package id, its canonical, the
    guide's own, and the path between them - and a disagreement surfaces late and indirectly, as a
    dependency the publisher cannot resolve or as every unit reference reported dangling. So both
    are derived here from the one identity `options` carries, and cannot disagree.

    `options` is the guide's: its id, canonical and selection are the guide's own. The registry
    takes the id with `.registry` appended and the canonical with `/registry`, publishes the
    organisation units alone, and carries no form selection - which is what
    `FhirProjectConfig` refuses a package for anyway.

    `max_level` reaches both on purpose. The guide's `[generate.organisation_units]` says which
    units its forms may refer to and the registry's says which it publishes; the two have to agree,
    and `d2w fhir check-artifacts` reports every reference where they do not.
    """
    guide = options.model_copy(update={"registry": _registry_dependency_for(options)})
    registry = _registry_options_for(options)
    files = [
        *_under(REGISTRY_RELATIVE_ROOT, build_scaffold_files(registry, copyright_year=copyright_year)),
        *_under(GUIDE_RELATIVE_ROOT, build_scaffold_files(guide, copyright_year=copyright_year)),
    ]
    year = copyright_year if copyright_year is not None else datetime.now(tz=UTC).year
    root = {"guide_root": GUIDE_RELATIVE_ROOT, "registry_root": REGISTRY_RELATIVE_ROOT, "year": year}
    return [
        *files,
        _render(MAKEFILE_RELATIVE_PATH, "guide-registry-Makefile.jinja", options, **root),
        _render(GUIDE_REGISTRY_README_RELATIVE_PATH, "guide-registry-README.md.jinja", options, **root),
    ]


def registry_id_for(ig_id: str) -> str:
    """The registry package's id, derived from the guide's so one `--id` decides both."""
    return f"{ig_id}.{_REGISTRY_ID_SUFFIX}"


def registry_canonical_for(canonical: str) -> str:
    """The registry package's canonical, derived from the guide's so one `--canonical` decides both."""
    return f"{canonical}/{REGISTRY_RELATIVE_ROOT}"


def _registry_dependency_for(options: InitOptions) -> RegistryDependency:
    """The dependency the guide states on the registry sitting beside it."""
    return RegistryDependency(
        id=registry_id_for(options.ig_id),
        canonical=registry_canonical_for(options.canonical),
        path=_REGISTRY_FROM_GUIDE,
    )


def _registry_options_for(options: InitOptions) -> InitOptions:
    """The registry package's own scaffold inputs, derived from the guide's identity.

    The selection tables are dropped rather than carried: a package publishes the organisation-unit
    registry and no form, and a package naming a data set is refused when its fhir.toml loads.
    `max_level` is the one selection value both keep, because both have to mean the same units.
    """
    return options.model_copy(
        update={
            "ig_id": registry_id_for(options.ig_id),
            "canonical": registry_canonical_for(options.canonical),
            "name": f"{options.name}Registry",
            "title": f"{options.title} - organisation unit registry",
            "kind": "package",
            "publishes": ORGANISATION_UNIT_PACKAGE,
            "registry": None,
            "data_set_ids": [],
            "event_program_ids": [],
            "tracker_program_ids": [],
        }
    )


def _under(root: str, files: list[ScaffoldFile]) -> list[ScaffoldFile]:
    """One project's scaffold, re-pathed under the directory it occupies.

    `init_project` writes every file at `directory / relative_path`, and a relative path may name
    a subdirectory, so both projects land under one parent without the writer knowing there are two.
    """
    return [
        scaffold_file.model_copy(update={"relative_path": f"{root}/{scaffold_file.relative_path}"})
        for scaffold_file in files
    ]


def _render(relative_path: str, template_name: str, options: InitOptions, **extra: object) -> ScaffoldFile:
    """Render one scaffold template with the IG identity plus any template-specific values."""
    content = _ENVIRONMENT.get_template(template_name).render(
        ig_id=options.ig_id,
        canonical=options.canonical,
        name=options.name,
        title=options.title,
        publisher=options.publisher,
        status=options.status,
        publisher_url=options.publisher_url,
        profile=options.profile,
        sushi_timeout=options.sushi_timeout,
        max_level=options.max_level,
        data_set_ids=options.data_set_ids,
        event_program_ids=options.event_program_ids,
        tracker_program_ids=options.tracker_program_ids,
        kind=options.kind,
        publishes=options.publishes,
        registry=options.registry,
        **extra,
    )
    return ScaffoldFile(relative_path=relative_path, content=content)
