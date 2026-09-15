"""Typer sub-app for the `fhir` plugin (mounted under `d2w fhir`).

Two output channels, one rule: every table, note, and progress line goes to
stderr through `STDERR_CONSOLE`, and stdout carries the `--json` payload alone.
A caller pipes stdout into `jq` without filtering anything out, and a human
reads the narration on the terminal either way.
"""

from __future__ import annotations

import asyncio
import errno
import os
import socket
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from dhis2w_core.cli_errors import CliUserError
from dhis2w_core.cli_output import ColumnSpec, DetailRow, is_json_output, render_detail, render_list
from dhis2w_core.progress import animated_progress, make_reporter
from dhis2w_core.rich_console import STDERR_CONSOLE
from pydantic import BaseModel, ConfigDict

from dhis2w_fhir import (
    DEFAULT_LOAD_SET_PER_TARGET,
    DEFAULT_SUSHI_TIMEOUT_SECONDS,
    MALFORMED_RESPONSES_RELATIVE_PATH,
    CorrectionPosture,
    GenerateReport,
    HostileNamePosture,
    OverwritePosture,
    ServeAuth,
    ServeAuthScope,
    WithdrawalPosture,
    load_project,
)
from dhis2w_fhir.doctor import DEFAULT_ORACLE_SAMPLES
from dhis2w_fhir.notes import GenerateNoteCategory
from dhis2w_fhir.resources.attribute_combos.restrictions import (
    UNTIMELY_ATTRIBUTE_OPTION_COMBO_REMEDY,
    UNUSABLE_ATTRIBUTE_OPTION_COMBO_REMEDY,
)
from dhis2w_fhir.resources.questionnaires.assignments import EMPTY_ASSIGNMENT_REMEDY
from dhis2w_fhir.status import ORGANISATION_UNIT_PACKAGE

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    from dhis2w_core.progress import ProgressReporter

    # Type-only, exactly as `d2w fhir serve` and `d2w fhir sync` import the package itself: the serve
    # extra may not be installed, and a name used in an annotation costs no import at runtime.
    from dhis2w_fhir_serve import ServeSettings, SyncReport

    from dhis2w_fhir.config import FhirProject, ProjectionConfig
    from dhis2w_fhir.doctor import DoctorReport
    from dhis2w_fhir.hostile_names import HostileNameGate, HostileRewrite
    from dhis2w_fhir.notes import GenerateNote
    from dhis2w_fhir.resources.organisation_units.schemas import RegistryDependency
    from dhis2w_fhir.scaffold.project_templates import ProjectTemplate
    from dhis2w_fhir.scaffold.schemas import ScaffoldReport
    from dhis2w_fhir.service import (
        ForwardOutcome,
        ForwardReport,
        GenerateFullReport,
        GenerationProfile,
        LoadSetReport,
        SpoolStateReport,
        WithdrawReport,
    )
    from dhis2w_fhir.validation.schemas import FhirValidationReport, ValidationFinding

app = typer.Typer(help="FHIR Implementation Guide generation from DHIS2 metadata.", no_args_is_help=True)
generate_app = typer.Typer()
app.add_typer(generate_app, name="generate")


class IgStatusChoice(StrEnum):
    """The IG life-cycle values `--status` accepts, mirroring the `IgStatus` literal."""

    DRAFT = "draft"
    ACTIVE = "active"


class PublishesChoice(StrEnum):
    """What `--publishes` accepts, mirroring the `PackageContent` literal.

    Naming it is what makes the project a package; a project that names nothing is a guide, which
    is why there is no `--kind` flag beside this one.
    """

    ORGANISATION_UNITS = "organisation-units"


#: The registry package version `d2w fhir init` seeds when the flags name a registry without one.
_DEFAULT_REGISTRY_VERSION = "0.1.0"


class CodeSourceChoice(StrEnum):
    """The concept code sources `--code-source` accepts, mirroring `[generate] concept_code_source`."""

    ID = "id"
    CODE = "code"


#: The detail-table title every generate target renders under, keyed by its command name.
_TARGET_TITLES = {
    "foundation": "fhir generate foundation",
    "option-sets": "fhir generate option-sets",
    "categories": "fhir generate categories",
    "questionnaires": "fhir generate questionnaires",
    "examples": "fhir generate examples",
    "org-units": "fhir generate org-units",
    "pages": "fhir generate pages",
    "load-set": "fhir generate load-set",
}

#: The Rich style each hint prefix carries, so a note reads as a note wherever it is printed.
_HINT_STYLES = {"note": "yellow", "ok": "green"}

#: The basename every validation report file is written under, inside `--output-dir`.
_VALIDATION_REPORT_STEM = "fhir-validate-report"

#: The report formats `--format` accepts, in the order they are written.
_REPORT_FORMATS = ("md", "csv", "pdf")

#: The scaffold defaults `--refresh` compares against to tell an untouched flag from a given one.
_DEFAULT_IG_ID = "dhis2.fhir.example"
_DEFAULT_CANONICAL = "http://example.org/fhir"
_DEFAULT_PUBLISHER = "Example Organisation"

#: The flag every long-running command narrates through, declared once and reused by each of them.
ProgressOption = Annotated[
    bool,
    typer.Option("--progress/--no-progress", help="Narrate each step on stderr as it completes."),
]


def _line(text: str) -> None:
    """Print one plain narration line on stderr, unwrapped so a path in it stays one selectable string."""
    STDERR_CONSOLE.print(text, markup=False, highlight=False, soft_wrap=True)


def _hint(prefix: str, text: str, *, style: str | None = None) -> None:
    """Print one `prefix: text` line on stderr, in the style that prefix carries unless one is given."""
    STDERR_CONSOLE.print(
        f"{prefix}: {text}",
        style=style or _HINT_STYLES.get(prefix),
        markup=False,
        highlight=False,
        soft_wrap=True,
    )


class GenerateDecisions(BaseModel):
    """The answers a `d2w fhir generate` flag preset, shared by the bare run and every named target."""

    model_config = ConfigDict(frozen=True)

    hostile_names: HostileNamePosture | None = None
    """What to do with a DHIS2 name carrying '<' and a DHIS2 code carrying a space; None asks."""


#: How many rewrites the warning block shows before it counts the rest. Enough to recognise the
#: shape of the names without turning the question into a report.
_HOSTILE_NAME_SAMPLE_SIZE = 10

#: The rule the warning block is drawn between, wide enough that it cannot be mistaken for a note.
_HOSTILE_NAME_RULE = "=" * 78


def _hostile_name_posture(*, substitute: bool, refuse: bool) -> HostileNamePosture | None:
    """The posture the two flags state, or None when neither was passed and the run asks instead."""
    if substitute and refuse:
        raise CliUserError(
            "--substitute-hostile-names and --refuse-hostile-names state opposite answers to the same "
            "question. Pass one of them, or neither to be asked."
        )
    if substitute:
        return HostileNamePosture.SUBSTITUTE
    return HostileNamePosture.REFUSE if refuse else None


def _generate_decisions(ctx: typer.Context) -> GenerateDecisions:
    """The decisions the generate group's flags preset, or the empty set when nothing was passed."""
    decisions = ctx.find_object(GenerateDecisions)
    return decisions if decisions is not None else GenerateDecisions()


def _hostile_name_gate(ctx: typer.Context, project: FhirProject) -> HostileNameGate:
    """The gate this run screens DHIS2 names through: the flag's answer, else the project's, else a question."""
    from dhis2w_fhir.hostile_names import project_gate

    return project_gate(project, override=_generate_decisions(ctx).hostile_names, confirmation=_confirm_hostile_names)


def _has_terminal() -> bool:
    """Whether there is a terminal to ask a question on, which a scripted run has not."""
    return sys.stdin.isatty()


def _confirm_hostile_names(rewrites: list[HostileRewrite]) -> bool:
    """Ask whether the guide may publish rewritten names and codes, and refuse without a terminal to ask on."""
    _print_hostile_name_warning(rewrites)
    if not _has_terminal():
        _line(
            "There is no terminal to ask on, so nothing is rewritten. Pass --substitute-hostile-names to "
            "publish the rewrites, or --refuse-hostile-names to refuse without being asked."
        )
        _line(_HOSTILE_NAME_RULE)
        return False
    _line(_HOSTILE_NAME_RULE)
    return typer.confirm("Rewrite these names and codes for publication?", default=False)


def _print_hostile_name_warning(rewrites: list[HostileRewrite]) -> None:
    """Print what the run found, what each rewrite changes, and what it leaves alone."""
    distinct = list({(rewrite.subject, rewrite.original): rewrite for rewrite in rewrites}.values())
    names = [rewrite for rewrite in distinct if rewrite.subject == "name"]
    codes = [rewrite for rewrite in distinct if rewrite.subject == "code"]
    _line("")
    _line(_HOSTILE_NAME_RULE)
    _line("DHIS2 names and codes the published guide rewrites")
    _line(_HOSTILE_NAME_RULE)
    if names:
        _print_hostile_name_finding(names)
    if codes:
        _print_hostile_code_finding(codes)
    _line(
        "Rewriting them changes the published guide and nothing else. DHIS2 is never modified: the instance "
        "keeps every name and code exactly as it stands, no UID is touched, every rewritten concept states "
        "its DHIS2 code as a `dhis2-code` property, and the ConceptMaps keep taking a published concept back "
        "to its DHIS2 object."
    )
    _line("")
    _print_hostile_sample(distinct)
    _line("")
    _line(
        "Leaving them publishes every name and code exactly as DHIS2 states it, which is what "
        '--refuse-hostile-names and `hostile_names = "refuse"` in fhir.toml do without asking. The run then '
        "refuses when one of the gated names carries '<', and `d2w fhir check-artifacts` reports what "
        "reaches the disk either way."
    )


def _print_hostile_name_finding(names: list[HostileRewrite]) -> None:
    """State what a DHIS2 name carrying '<' costs the guide's build."""
    from dhis2w_fhir.notes import pluralize, verb_for_count

    _line(
        f"{pluralize(len(names), 'selected DHIS2 name')} "
        f"{verb_for_count(len(names), 'carries', 'carry')} '<'. A name reaches the guide byte-true, and "
        "the IG publisher writes it into pages it strict-parses after writing, so `make build` aborts in its "
        "last pass, once every resource has already been rendered."
    )
    _line("")


def _print_hostile_code_finding(codes: list[HostileRewrite]) -> None:
    """State what a DHIS2 code carrying a space costs the guide and everything downstream of it."""
    from dhis2w_fhir.notes import pluralize, verb_for_count

    _line(
        f"{pluralize(len(codes), 'selected DHIS2 code')} "
        f"{verb_for_count(len(codes), 'carries', 'carry')} a space. A space is legal in an R4 code, so "
        "nothing refuses it - but the IG publisher's anchor slug strips whitespace, so 'Pre eclampsia' and "
        "'Preeclampsia' render one anchor id, and every URL, CQL quotation, and terminology server "
        "downstream handles the space at its own discretion. Each space becomes a hyphen."
    )
    _line("")


def _print_hostile_sample(distinct: list[HostileRewrite]) -> None:
    """Show a sample of the rewrites, each labelled by whether it is a name or a code."""
    shown = distinct[:_HOSTILE_NAME_SAMPLE_SIZE]
    remainder = len(distinct) - len(shown)
    _line("As they would be published:" if not remainder else f"{len(shown)} of them, as they would be published:")
    for rewrite in shown:
        _line(f"  {rewrite.subject}: {rewrite.original!r} -> {rewrite.rewritten!r}")
    if remainder:
        _line(f"  and {remainder} more.")


@contextmanager
def _progress(total: int, *, enabled: bool) -> Generator[ProgressReporter | None]:
    """Yield the reporter a run narrates its `total` steps through, torn down on every exit path.

    None when the run stays quiet - `--no-progress`, or `--json`, where stderr carries nothing
    so a caller reads the payload off stdout without filtering. The service treats a missing
    reporter as "announce to nothing", so the same call works either way.
    """
    if not enabled or is_json_output():
        yield None
        return
    reporter = make_reporter(STDERR_CONSOLE, animated=animated_progress(enabled))
    reporter.start(total, activity="step")
    try:
        yield reporter
    finally:
        reporter.stop()


@app.command("init")
def init_command(
    directory: Annotated[
        Path, typer.Argument(file_okay=False, help="Project directory (default: current directory).")
    ] = Path("."),
    template: Annotated[
        str | None,
        typer.Option(
            "--template",
            help="Scaffold from a guide already generated against a real DHIS2 instance, so the project "
            "compiles and serves without reaching one. The template supplies the identity and the "
            "selection; --id, --canonical, --name, --title, --publisher and --status win over it. "
            "`--list-templates` names what this install carries.",
        ),
    ] = None,
    list_templates: Annotated[
        bool,
        typer.Option(
            "--list-templates",
            help="Name every template this install can scaffold from, one line each, and exit.",
        ),
    ] = False,
    ig_id: Annotated[str, typer.Option("--id", help="IG package id.")] = _DEFAULT_IG_ID,
    canonical: Annotated[
        str, typer.Option("--canonical", help="Canonical base URL for the IG (no trailing slash).")
    ] = _DEFAULT_CANONICAL,
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help="SUSHI name (default: derived from --id). FHIR computer-friendly: an upper-case letter, "
            "then up to 254 letters, digits or underscores. SUSHI rewrites anything else without "
            "saying so, so a name outside that shape is refused here.",
        ),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            help="IG title (default: derived from --name). A title carrying '<' or '>' is refused: the IG "
            "publisher strict-parses the pages it writes the title into, and aborts the build in its "
            "last pass.",
        ),
    ] = None,
    publisher: Annotated[str, typer.Option("--publisher", help="Publisher name.")] = _DEFAULT_PUBLISHER,
    status: Annotated[
        IgStatusChoice,
        typer.Option(
            "--status",
            help="IG life cycle. Drives the sushi-config status, and the status and experimental flag "
            "on every generated definitional resource.",
        ),
    ] = IgStatusChoice.DRAFT,
    publisher_url: Annotated[
        str | None,
        typer.Option(
            "--publisher-url",
            help="Publisher home page. Omit it unless you have a real site: the IG publisher links it from "
            "every generated page, and pointing it at the canonical yields one broken link per page.",
        ),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            help="DHIS2 profile to seed the `profile` key of the scaffolded fhir.toml with, so "
            "`d2w fhir generate` reads that instance without a flag. Offline: the name is written as "
            "given, never resolved against profiles.toml.",
        ),
    ] = None,
    sushi_timeout: Annotated[
        int,
        typer.Option(
            "--sushi-timeout",
            help="Seconds the IG publisher gives its internal SUSHI run, written to `\\[FSH] timeout` of "
            "ig/fsh.ini. It bounds the FSH targets alone - the registry and the terminology ship as "
            "pre-built JSON - and an overrun fails the build with exit 143.",
        ),
    ] = DEFAULT_SUSHI_TIMEOUT_SECONDS,
    max_level: Annotated[
        int | None,
        typer.Option(
            "--max-level",
            help="Deepest organisation-unit level to generate, seeding `\\[generate.organisation_units]` "
            "max_level. A hierarchy fans out at the bottom and every unit emits two instances, so this "
            "is the dial that bounds how much the IG publisher renders. Offline: written as given.",
        ),
    ] = None,
    data_set_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--data-set",
            help="Data set UID to seed `\\[generate.data_sets]` include_ids with (repeatable). Naming one "
            "family narrows that family alone: a selection table that is absent - or whose include_ids is an "
            "empty list - means every member of its kind, so a guide naming data sets here still publishes "
            "every event program and every tracker program. Narrow those with --event-program and "
            "--tracker-program, or by writing `\\[generate.event_programs]` and "
            "`\\[generate.tracker_programs]` in fhir.toml; `enabled = false` is what publishes none of a kind. "
            "Offline: the UID shape is checked here, never the instance.",
        ),
    ] = None,
    event_program_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--event-program",
            help="Event program UID to seed `\\[generate.event_programs]` include_ids with (repeatable). Naming "
            "one family narrows that family alone: a selection table that is absent - or whose include_ids is "
            "an empty list - means every member of its kind, so a guide naming event programs here still "
            "publishes every data set and every tracker program. Narrow those with --data-set and "
            "--tracker-program, or by writing `\\[generate.data_sets]` and `\\[generate.tracker_programs]` "
            "in fhir.toml; `enabled = false` is what publishes none of a kind. Offline: the UID shape is "
            "checked here, never the instance.",
        ),
    ] = None,
    tracker_program_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--tracker-program",
            help="Tracker program UID to seed `\\[generate.tracker_programs]` include_ids with (repeatable); the "
            "program emits one Questionnaire per program stage. Naming one family narrows that family "
            "alone: a selection table that is absent - or whose include_ids is an empty list - means every "
            "member of its kind, so a guide naming tracker programs here still publishes every data set and "
            "every event program. Narrow those with --data-set and --event-program, or by writing "
            "`\\[generate.data_sets]` and `\\[generate.event_programs]` in fhir.toml; `enabled = false` is "
            "what publishes none of a kind. Offline: the UID shape is checked here, never the instance.",
        ),
    ] = None,
    publishes: Annotated[
        PublishesChoice | None,
        typer.Option(
            "--publishes",
            help="Scaffold a package rather than a guide, holding what this names and nothing else, "
            "for guides to depend on through --registry-id. `organisation-units` is the registry "
            "package. Omit it to scaffold a guide, which is the default.",
        ),
    ] = None,
    with_registry: Annotated[
        bool,
        typer.Option(
            "--with-registry",
            help="Scaffold the guide and the organisation-unit registry package it depends on, as two "
            "wired projects under this directory: `registry/` publishes the units, `guide/` publishes "
            "the forms and references them. Both identities derive from --id and --canonical, so they "
            "cannot disagree, and a Makefile beside them drives the pair in the order that resolves.",
        ),
    ] = False,
    registry_id: Annotated[
        str | None,
        typer.Option(
            "--registry-id",
            help="Package id of the registry package this guide's organisation units are published by, "
            "seeding `\\[generate.organisation_units.registry]`; the guide then writes no Organization or "
            "Location of its own. Needs --registry-canonical.",
        ),
    ] = None,
    registry_canonical: Annotated[
        str | None,
        typer.Option(
            "--registry-canonical",
            help="Canonical base URL of the registry package (no trailing slash); every reference to a unit is "
            "a URL under it. Needs --registry-id.",
        ),
    ] = None,
    registry_version: Annotated[
        str | None,
        typer.Option(
            "--registry-version",
            help=f"Version of the registry package `make build` installs and depends on (default: "
            f"{_DEFAULT_REGISTRY_VERSION}).",
        ),
    ] = None,
    registry_path: Annotated[
        Path | None,
        typer.Option(
            "--registry-path",
            file_okay=False,
            help="Local checkout of the registry project, whose build wrote the package `make build` "
            "installs. Written as given, relative to the new project's directory, and refused when no "
            "directory stands there.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite scaffold files that already exist, fhir.toml and every hand-written line in "
            "them included. Each is reported overwritten and named, and the run says what it replaced.",
        ),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Bring an existing project's scaffold-managed files up to date. Identity comes from the "
            "project's own fhir.toml, which a refresh never writes. Five toolchain files are the "
            "scaffold's own and are rewritten whole from the current render - the Makefile, the "
            "Dockerfile, .python-version, ig/ig.ini and ig/fsh.ini - so an edit to one of them does not "
            "survive: every knob the Makefile has is a `?=` default, and a value you set on the command "
            "line (`make build JAVA_HEAP=8g`) or in the environment lives outside the file. "
            "fhir.example.toml is graded on the keys it sets rather than on the sentences explaining "
            "them: the prose is the scaffold's and is re-worded release by release, so a key you set "
            "there is kept and a comment you wrote is not. Every other file carrying a line the "
            "scaffold would not produce is left alone and reported, so your edits to those survive. "
            "Rejects --force.",
        ),
    ] = False,
) -> None:
    """Scaffold a dockerized SUSHI IG project with a fhir.toml for `d2w fhir generate`."""
    from dhis2w_fhir import InitOptions, service

    if list_templates:
        _list_project_templates()
        return
    if refresh and force:
        raise typer.BadParameter(
            "--refresh and --force are mutually exclusive: --force rewrites every scaffold file including "
            "the ones you edited, --refresh rewrites only what it can rewrite without losing your edits"
        )
    if refresh:
        if template is not None:
            raise typer.BadParameter(
                "--refresh and --template are mutually exclusive: a refresh brings an existing "
                "project's scaffold-managed files up to date, and a template pre-populates a new one"
            )
        _reject_scaffold_flags(
            ig_id=ig_id,
            canonical=canonical,
            name=name,
            title=title,
            publisher=publisher,
            status=status,
            publisher_url=publisher_url,
            profile=profile,
            sushi_timeout=sushi_timeout,
            max_level=max_level,
            data_set_ids=data_set_ids,
            event_program_ids=event_program_ids,
            tracker_program_ids=tracker_program_ids,
            publishes=publishes,
            with_registry=with_registry,
            registry_id=registry_id,
            registry_canonical=registry_canonical,
            registry_version=registry_version,
            registry_path=registry_path,
        )
        _refresh_project(directory)
        return
    if max_level is not None and max_level < 1:
        raise typer.BadParameter("--max-level must be 1 or greater")
    if with_registry:
        _reject_with_registry_conflicts(
            publishes=publishes,
            template=template,
            registry_id=registry_id,
            registry_canonical=registry_canonical,
            registry_version=registry_version,
            registry_path=registry_path,
        )
    _require_uid_shape("--data-set", data_set_ids)
    _require_uid_shape("--event-program", event_program_ids)
    _require_uid_shape("--tracker-program", tracker_program_ids)
    _require_registry_checkout(directory, registry_path)
    registry = _registry_dependency(
        publishes=publishes,
        registry_id=registry_id,
        registry_canonical=registry_canonical,
        registry_version=registry_version,
        registry_path=registry_path,
        data_set_ids=data_set_ids,
        event_program_ids=event_program_ids,
        tracker_program_ids=tracker_program_ids,
    )
    project_template = _resolve_project_template(template) if template is not None else None
    if project_template is not None:
        if publishes is not None:
            raise typer.BadParameter(
                f"--template {project_template.name} ships a guide of forms, which a package publishes "
                f"none of: drop --publishes {publishes.value}, or scaffold the package without a template"
            )
        _reject_selection_flags(
            template=project_template.name,
            max_level=max_level,
            data_set_ids=data_set_ids,
            event_program_ids=event_program_ids,
            tracker_program_ids=tracker_program_ids,
        )
        if ig_id == _DEFAULT_IG_ID:
            ig_id = project_template.ig_id
            name = name or project_template.ig_name
            title = title or project_template.title
        if canonical == _DEFAULT_CANONICAL:
            canonical = project_template.canonical
    resolved_name = name or _derived_ig_name(ig_id)
    resolved_title = title or f"{resolved_name} Implementation Guide"
    _require_parseable_page_text("--name", resolved_name)
    _require_parseable_page_text("--title", resolved_title)
    _require_fhir_name(resolved_name, flag="--name" if name else "--id")
    options = InitOptions(
        ig_id=ig_id,
        canonical=canonical,
        name=resolved_name,
        title=resolved_title,
        publisher=publisher,
        status="active" if status is IgStatusChoice.ACTIVE else "draft",
        publisher_url=publisher_url,
        profile=profile,
        sushi_timeout=sushi_timeout,
        max_level=max_level,
        data_set_ids=data_set_ids or [],
        event_program_ids=event_program_ids or [],
        tracker_program_ids=tracker_program_ids or [],
        kind="package" if publishes is not None else "guide",
        publishes=ORGANISATION_UNIT_PACKAGE if publishes is PublishesChoice.ORGANISATION_UNITS else None,
        registry=registry,
    )
    report = asyncio.run(
        service.init_project(directory, options, force=force, template=project_template, with_registry=with_registry)
    )
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    rows = [
        DetailRow("directory", str(report.directory)),
        DetailRow("created", str(len(report.created_files))),
        DetailRow("overwritten", str(len(report.overwritten_files))),
        DetailRow("skipped", str(len(report.skipped_files))),
    ]
    if project_template is not None:
        rows.append(DetailRow("template", project_template.name))
        rows.append(DetailRow("template files", str(len(report.template_files))))
        rows.append(DetailRow("template files overwritten", str(len(report.overwritten_template_files))))
        rows.append(DetailRow("template files skipped", str(len(report.skipped_template_files))))
    render_detail("fhir init", rows, console=STDERR_CONSOLE)
    for relative_path in report.created_files:
        _line(f"  created {relative_path}")
    for relative_path in report.overwritten_files:
        _line(f"  overwritten {relative_path}")
    for relative_path in report.skipped_files:
        _line(f"  skipped {relative_path} (exists; use --force to overwrite)")
    _print_force_discards(report)
    if project_template is not None:
        _print_template_next_steps(project_template, report, directory)
        return
    if with_registry:
        _print_with_registry_next_steps(directory, profile=profile)
        return
    if profile:
        _hint("next", f"run `d2w fhir generate` (profile `{profile}`)")
    else:
        _hint("next", "set `profile` in fhir.toml, then run `d2w fhir generate`")


def _print_with_registry_next_steps(directory: Path, *, profile: str | None) -> None:
    """Say what two wired projects need next, which is not what one project needs.

    The order is the part worth stating: the registry writes the package the guide's build installs,
    so a guide built first has a dependency the publisher cannot resolve. The Makefile beside them
    encodes that, which is why the hint names it rather than the two builds.
    """
    from dhis2w_fhir.scaffold import GUIDE_RELATIVE_ROOT, REGISTRY_RELATIVE_ROOT

    _hint("info", f"{REGISTRY_RELATIVE_ROOT}/ publishes the organisation units; {GUIDE_RELATIVE_ROOT}/ the forms")
    if not profile:
        _hint("next", f"set `profile` in {REGISTRY_RELATIVE_ROOT}/fhir.toml and {GUIDE_RELATIVE_ROOT}/fhir.toml")
    _hint("next", f"cd {directory} && make generate, then `make build` - the registry builds first")


def _print_force_discards(report: ScaffoldReport) -> None:
    """Say what `--force` replaced, so a run that rewrote a project reads as a rewrite rather than a scaffold.

    The scaffold's own files are named line by line above, so the closing line counts them; a
    template payload is hundreds of files wide and is counted rather than named.
    """
    scaffold_files = len(report.overwritten_files)
    payload_files = len(report.overwritten_template_files)
    if not scaffold_files and not payload_files:
        return
    replaced = f"{scaffold_files} file(s) that already stood here, listed above"
    if payload_files:
        replaced = f"{scaffold_files} scaffold file(s), listed above, and {payload_files} template file(s)"
    _hint(
        "note",
        f"--force replaced {replaced} - what they held, fhir.toml and every hand-written line included, is gone",
    )


def _derived_ig_name(ig_id: str) -> str:
    """The SUSHI name `--id` yields on its own: PascalCase, bounded to the 255 characters FHIR allows."""
    from dhis2w_fhir.names import FHIR_NAME_MAX_LENGTH, pascal

    return pascal(ig_id)[:FHIR_NAME_MAX_LENGTH]


def _require_fhir_name(value: str, *, flag: str) -> None:
    """Refuse a SUSHI name outside the FHIR computer-friendly shape, stating the rule and what SUSHI does."""
    from dhis2w_fhir.names import is_fhir_name

    if is_fhir_name(value):
        return
    raise typer.BadParameter(
        f"{flag} yields the SUSHI name `{value}`, which FHIR does not accept: a name is an upper-case "
        f"letter followed by up to 254 letters, digits or underscores. SUSHI rewrites anything else "
        f"without saying so, and the guide then publishes a name nobody chose."
    )


def _require_parseable_page_text(flag: str, value: str) -> None:
    """Refuse a title or name carrying '<' or '>', the two characters that abort the IG publisher's last pass."""
    for character in ("<", ">"):
        if character in value:
            raise typer.BadParameter(
                f"{flag} carries '{character}'. The IG publisher writes this value into pages it "
                f"strict-parses after writing, so the build aborts in its last pass, once every resource "
                f"has already been rendered. Name it without '<' and '>'."
            )


def _require_uid_shape(flag: str, uids: list[str] | None) -> None:
    """Refuse a selection UID outside the DHIS2 shape, so a typo is caught here rather than as an empty guide."""
    from dhis2w_fhir.names import is_dhis2_uid

    malformed = [uid for uid in uids or [] if not is_dhis2_uid(uid)]
    if not malformed:
        return
    raise typer.BadParameter(
        f"{flag} carries {', '.join(repr(uid) for uid in malformed)}, which is not a DHIS2 UID: eleven "
        f"characters, an ASCII letter followed by ten letters or digits."
    )


def _require_registry_checkout(directory: Path, registry_path: Path | None) -> None:
    """Refuse a `--registry-path` no directory stands at, resolved the way the scaffolded fhir.toml reads it.

    The path is normalised rather than resolved: the project directory is what this run is about to
    write, so `..` is folded textually and no `.resolve()` is asked of a directory that does not
    exist yet.
    """
    if registry_path is None:
        return
    resolved = registry_path if registry_path.is_absolute() else Path(os.path.normpath(directory / registry_path))
    if resolved.is_dir():
        return
    raise typer.BadParameter(
        f"--registry-path {registry_path} names no directory: the project reads it from its own root, "
        f"which puts it at {resolved}. Scaffold the registry project there first, or drop the flag and "
        f"let `make build` install the package from its id and version."
    )


def _resolve_project_template(name: str) -> ProjectTemplate:
    """Resolve `--template`, turning a name this install will not scaffold into a user error stating why."""
    from dhis2w_fhir.scaffold.project_templates import TemplateUnavailableError, resolve_template

    try:
        return resolve_template(name)
    except TemplateUnavailableError as error:
        raise CliUserError(str(error)) from error


def _list_project_templates() -> None:
    """Render every template this install can scaffold from, one row each, off the template manifest."""
    from dhis2w_fhir.scaffold.project_templates import list_templates

    templates = list_templates()
    if is_json_output():
        typer.echo(f"[{','.join(template.model_dump_json() for template in templates)}]")
        return
    render_list(
        "fhir init --template",
        [
            {
                "template": template.name,
                "ships in": template.origin.value,
                "publishes": template.summary,
            }
            for template in templates
        ],
        [
            ColumnSpec("template", "template", no_wrap=True),
            ColumnSpec("ships in", "ships in", no_wrap=True),
            ColumnSpec("publishes", "publishes"),
        ],
        console=STDERR_CONSOLE,
    )
    _hint(
        "note",
        "a bundled template rides the installed package; a checkout one is read from "
        "examples/fhir/igs/ of the dhis2w repository and exists only in a clone of it",
    )


def _print_template_next_steps(template: ProjectTemplate, report: ScaffoldReport, directory: Path) -> None:
    """State what a template-scaffolded project already holds and the one step between it and a facade.

    A checkout template's `ig/input/` tree is generated rather than committed, so a checkout that
    has never generated it lays down nothing. The project is then the ordinary scaffold and takes
    the ordinary next step - naming `make sushi` there would name a compile with no source.
    """
    laid_down = len(report.template_files) + len(report.overwritten_template_files)
    _line(f"  laid down {laid_down} files from template `{template.name}` under ig/input/")
    if report.skipped_template_files:
        _line(
            f"  left {len(report.skipped_template_files)} template files alone (they exist; use --force to overwrite)"
        )
    if not laid_down and not report.skipped_template_files:
        _hint(
            "note",
            f"`{template.name}` keeps its ig/input/ tree generated rather than committed, and this "
            f"checkout has not generated it - `make verify-igs` writes it. The project holds the "
            f"scaffold alone until then.",
        )
        _hint("next", "set `profile` in fhir.toml, then run `d2w fhir generate`")
        return
    _hint(
        "note", "the guide under ig/input/ was generated against a DHIS2 instance already - none is needed to serve it"
    )
    _hint("next", f"cd {directory} && make sushi, then `d2w fhir serve . --ui`")


def _reject_selection_flags(
    *,
    template: str,
    max_level: int | None,
    data_set_ids: list[str] | None,
    event_program_ids: list[str] | None,
    tracker_program_ids: list[str] | None,
) -> None:
    """Refuse a template scaffold that also names a selection, naming the flags that would disagree with it.

    A template ships the tree its own selection produced. Writing a different selection into
    `fhir.toml` beside that tree states one thing in the configuration and another in the files, and
    the project would serve the template's guide while claiming to publish something else. The way
    to a selection of your own is to scaffold, edit `fhir.toml`, and run `d2w fhir generate` against
    an instance that holds it.
    """
    given = {
        "--max-level": max_level is not None,
        "--data-set": bool(data_set_ids),
        "--event-program": bool(event_program_ids),
        "--tracker-program": bool(tracker_program_ids),
    }
    named = [flag for flag, was_given in given.items() if was_given]
    if not named:
        return
    raise typer.BadParameter(
        f"--template {template} ships the guide its own selection produced, so {', '.join(named)} would "
        f"write a fhir.toml that disagrees with the tree beside it: drop the flag, or scaffold first and "
        f"then edit fhir.toml and run `d2w fhir generate`"
    )


def _registry_dependency(
    *,
    publishes: PublishesChoice | None,
    registry_id: str | None,
    registry_canonical: str | None,
    registry_version: str | None,
    registry_path: Path | None,
    data_set_ids: list[str] | None,
    event_program_ids: list[str] | None,
    tracker_program_ids: list[str] | None,
) -> RegistryDependency | None:
    """The registry package the `--registry-*` flags name, or None - refusing a half-named one.

    A registry package publishes the registry itself and no form, so it takes neither the
    `--registry-*` flags nor a data set or program; a guide naming a registry needs at least the
    package id and its canonical, since both go into `sushi-config.yaml` and every reference.
    """
    from dhis2w_fhir.resources.organisation_units.schemas import RegistryDependency

    given = {
        "--registry-id": registry_id is not None,
        "--registry-canonical": registry_canonical is not None,
        "--registry-version": registry_version is not None,
        "--registry-path": registry_path is not None,
    }
    named = [flag for flag, was_given in given.items() if was_given]
    if publishes is not None:
        if named:
            raise typer.BadParameter(
                f"--publishes {publishes.value} scaffolds the package itself, which depends on no package: "
                f"drop {', '.join(named)}"
            )
        selection = {
            "--data-set": bool(data_set_ids),
            "--event-program": bool(event_program_ids),
            "--tracker-program": bool(tracker_program_ids),
        }
        selected = [flag for flag, was_given in selection.items() if was_given]
        if selected:
            raise typer.BadParameter(
                f"--publishes {publishes.value} publishes the organisation-unit registry alone and no form: "
                f"drop {', '.join(selected)}"
            )
        return None
    if not named:
        return None
    if registry_id is None or registry_canonical is None:
        raise typer.BadParameter(
            f"{', '.join(named)} names a registry package, which takes both --registry-id and "
            "--registry-canonical: the id is what the publisher installs, the canonical is what every reference "
            "to a unit is a URL under"
        )
    return RegistryDependency(
        id=registry_id,
        canonical=registry_canonical,
        version=registry_version if registry_version is not None else _DEFAULT_REGISTRY_VERSION,
        path=registry_path,
    )


def _reject_with_registry_conflicts(
    *,
    publishes: PublishesChoice | None,
    template: str | None,
    registry_id: str | None,
    registry_canonical: str | None,
    registry_version: str | None,
    registry_path: Path | None,
) -> None:
    """Refuse a `--with-registry` run carrying flags it would have to contradict.

    The flag scaffolds a guide and derives the registry beside it, so a stated package content, a
    template, or a registry named by hand each say something the derivation would overwrite.
    """
    if publishes is not None:
        raise typer.BadParameter(
            f"--with-registry scaffolds a guide and the registry package it depends on; "
            f"--publishes {publishes.value} scaffolds that package alone. Drop one."
        )
    if template is not None:
        raise typer.BadParameter(
            f"--template {template} ships one project's guide, and --with-registry scaffolds two: "
            "drop --template, or scaffold the guide from the template and its registry separately"
        )
    named = [
        flag
        for flag, was_given in (
            ("--registry-id", registry_id is not None),
            ("--registry-canonical", registry_canonical is not None),
            ("--registry-version", registry_version is not None),
            ("--registry-path", registry_path is not None),
        )
        if was_given
    ]
    if named:
        raise typer.BadParameter(
            f"--with-registry derives the registry package from --id and --canonical, so the two "
            f"projects cannot disagree: drop {', '.join(named)}"
        )


def _reject_scaffold_flags(
    *,
    ig_id: str,
    canonical: str,
    name: str | None,
    title: str | None,
    publisher: str,
    status: IgStatusChoice,
    publisher_url: str | None,
    profile: str | None,
    sushi_timeout: int,
    max_level: int | None,
    data_set_ids: list[str] | None,
    event_program_ids: list[str] | None,
    tracker_program_ids: list[str] | None,
    publishes: PublishesChoice | None,
    with_registry: bool,
    registry_id: str | None,
    registry_canonical: str | None,
    registry_version: str | None,
    registry_path: Path | None,
) -> None:
    """Refuse a refresh that carries scaffold content, naming the flags a refresh would ignore.

    A refresh reads the IG identity and the generation tables back off the project's own
    fhir.toml, and never writes that file, so a flag seeding either of them cannot land. Silently
    dropping it would leave a caller believing they changed something they did not.
    """
    given = {
        "--id": ig_id != _DEFAULT_IG_ID,
        "--canonical": canonical != _DEFAULT_CANONICAL,
        "--name": name is not None,
        "--title": title is not None,
        "--publisher": publisher != _DEFAULT_PUBLISHER,
        "--status": status is not IgStatusChoice.DRAFT,
        "--publisher-url": publisher_url is not None,
        "--profile": profile is not None,
        "--sushi-timeout": sushi_timeout != DEFAULT_SUSHI_TIMEOUT_SECONDS,
        "--max-level": max_level is not None,
        "--data-set": bool(data_set_ids),
        "--event-program": bool(event_program_ids),
        "--tracker-program": bool(tracker_program_ids),
        "--publishes": publishes is not None,
        "--with-registry": with_registry,
        "--registry-id": registry_id is not None,
        "--registry-canonical": registry_canonical is not None,
        "--registry-version": registry_version is not None,
        "--registry-path": registry_path is not None,
    }
    named = [flag for flag, was_given in given.items() if was_given]
    if not named:
        return
    raise typer.BadParameter(
        f"--refresh takes the project's identity and generation tables from its own fhir.toml, "
        f"so {', '.join(named)} would be ignored: drop the flag, or edit fhir.toml and refresh"
    )


def _refresh_project(directory: Path) -> None:
    """Refresh an existing project's scaffold-managed files and render what each one did."""
    from dhis2w_fhir.config import FHIR_CONFIG_FILENAME
    from dhis2w_fhir.scaffold.refresh import refresh_project

    report = refresh_project(directory)
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    render_detail(
        "fhir init --refresh",
        [
            DetailRow("directory", str(report.directory)),
            DetailRow("created", str(len(report.created_files))),
            DetailRow("rewritten (scaffold-owned)", str(len(report.rewritten_files))),
            DetailRow("refreshed", str(len(report.refreshed_files))),
            DetailRow("refreshed, with your additions", str(len(report.refreshed_with_additions_files))),
            DetailRow("unchanged", str(len(report.unchanged_files))),
            DetailRow("with your additions", str(len(report.extended_files))),
            DetailRow("diverged (kept)", str(len(report.diverged_files))),
        ],
        console=STDERR_CONSOLE,
    )
    for relative_path in report.created_files:
        _line(f"  created {relative_path}")
    for relative_path in report.rewritten_files:
        _line(f"  rewritten {relative_path} (scaffold-owned; an edit to it does not survive a refresh)")
    for relative_path in report.refreshed_files:
        _line(f"  refreshed {relative_path}")
    # Both halves of the verdict, in the order they happened: the render's identity line landed,
    # and the lines the reader wrote are still under it.
    for relative_path in report.refreshed_with_additions_files:
        _line(
            f"  refreshed, with your additions {relative_path} "
            "(the current identity landed; every line of your own is still there)"
        )
    for relative_path in report.unchanged_files:
        _line(f"  unchanged {relative_path}")
    # The two verdicts the table separates are separate here too: "kept" for both would teach a
    # distinction in the summary and drop it in the detail, which is where a reader looks for it.
    for relative_path in report.extended_files:
        _line(f"  with your additions {relative_path} (carries every current scaffold line, plus lines of your own)")
    for relative_path in report.diverged_files:
        _line(f"  diverged (kept) {relative_path} (holds lines the current scaffold does not write)")
    _hint("note", f"{FHIR_CONFIG_FILENAME} is yours - a refresh never writes it")
    if report.rewritten_files:
        _hint(
            "note",
            "a scaffold-owned file is the toolchain's, and the render replaces it whole - the Makefile, "
            "the Dockerfile, .python-version, ig/ig.ini and ig/fsh.ini. Keep a value of your own out of "
            "them: every Makefile knob is a `?=` default, so set it on the command line "
            "(`make build JAVA_HEAP=8g`) or in the environment.",
        )
    for note in report.notes:
        _hint("note", note)
    if report.diverged_files:
        _hint(
            "note",
            "a diverged file holds your edits, or scaffold lines that have since changed - this refresh "
            "cannot tell which. To take the scaffold's version, delete the file and refresh again; lines "
            "of your own in it go with it.",
        )


class _TargetOutcome(BaseModel):
    """One target of a full run, paired with the command name its summary row is labelled by."""

    model_config = ConfigDict(frozen=True)

    target: str
    report: GenerateReport


def _target_label(report: GenerateReport | LoadSetReport) -> str:
    """Where a run wrote, as one path: a generate target carries its base, a load set is the corpus directory."""
    if isinstance(report, GenerateReport):
        return f"{report.target_base}/{report.target_directory}"
    return report.target_directory


def _render_generate_report(
    title: str,
    report: GenerateReport | LoadSetReport,
    generation: GenerationProfile,
    *,
    extra_rows: Iterable[DetailRow] = (),
) -> None:
    """Render one run's outcome as a detail table on stderr, followed by every note it raised.

    The common rows - profile, project, target, and the files written / unchanged / deleted -
    are the same whichever run wrote them; `extra_rows` carries the counts that belong to this
    target alone. Every row renders at zero too, so a table's shape says what a target counts
    rather than what it happened to find.
    """
    rows = [
        DetailRow("profile", f"{generation.name} ({generation.origin})"),
        DetailRow("project", str(report.project_root)),
        DetailRow("target", _target_label(report)),
        DetailRow("files written", f"{len(report.written_files):,}"),
        DetailRow("files unchanged", f"{report.unchanged_count:,}"),
        DetailRow("files deleted", f"{len(report.deleted_files):,}"),
        *extra_rows,
    ]
    render_detail(title, rows, console=STDERR_CONSOLE)
    for note in report.notes:
        _hint("note", note.message)
    _render_empty_assignments(report)
    _render_unusable_attribute_option_combos(report)
    _render_untimely_attribute_option_combos(report)
    _render_computed_questions(report)


def _render_empty_assignments(report: GenerateReport | LoadSetReport) -> None:
    """Say out loud that a run published forms no organisation unit may report, when it did.

    Its own line at the end of the run, rather than one note among the several hundred a national
    instance raises: a form nobody can submit is not a detail of the terminology, and a reader who
    chose `max_level` to keep a build small has no other way to learn what it cost.

    The line names the data sets and programs the assignment hangs on, the way the combo warnings
    name their forms: a count alone sends a reader to the notes file for the one fact that decides
    what to do next - whether the object they came for is the one nobody may report.
    """
    if not isinstance(report, GenerateReport) or report.empty_assignments is None:
        return
    summary = report.empty_assignments
    narrowed = (
        f" under [generate.organisation_units] max_level {summary.max_level}" if summary.max_level is not None else ""
    )
    _hint(
        "warning",
        f"{summary.form_count} published form(s) carry an empty organisation-unit assignment{narrowed}: no "
        f"organisation unit may report them, and the facade refuses to draft a response for one. "
        f"The assignment hangs on: {', '.join(summary.containers)}. {EMPTY_ASSIGNMENT_REMEDY}",
        style="yellow",
    )


def _render_unusable_attribute_option_combos(report: GenerateReport | LoadSetReport) -> None:
    """Say out loud that a run published forms every attribute option combo of theirs is restricted away from.

    Its own line at the end of the run, for the reason the empty-assignment warning has one: DHIS2
    refuses every capture such a form could carry, the run knows it at generate time from the
    restriction Lists it just wrote, and a reader who chose `max_level` to keep a build small has no
    other way to learn what it cost.

    The line names the forms. A count alone sends a reader to the notes file for the one fact that
    decides what to do next - whether the form they came for is the one nobody may submit.
    """
    if not isinstance(report, GenerateReport) or report.unusable_attribute_option_combos is None:
        return
    summary = report.unusable_attribute_option_combos
    narrowed = (
        f" under [generate.organisation_units] max_level {summary.max_level}" if summary.max_level is not None else ""
    )
    _hint(
        "warning",
        f"{summary.form_count} published form(s) declare attribute option combos DHIS2 restricts away from every "
        f"organisation unit that may report them{narrowed}: no capture for one of them can be keyed to a combo "
        f"this DHIS2 instance accepts, and the facade refuses to draft a response for one. "
        f"They are: {', '.join(summary.forms)}. {UNUSABLE_ATTRIBUTE_OPTION_COMBO_REMEDY}",
        style="yellow",
    )


def _render_untimely_attribute_option_combos(report: GenerateReport | LoadSetReport) -> None:
    """Say out loud that a run published forms every attribute option combo of theirs has closed for.

    The date axis's own line, for the reason the unit axis has one: DHIS2 scopes a category option
    to a calendar window as well as to organisation units, refuses a capture the window does not
    cover entirely, and a form whose every combo closed before the periods it reports is as dead as
    one restricted away from every organisation unit.

    The line names the forms, and its remedy says plainly where the fix is: a category option's
    window is DHIS2 metadata, and no fhir.toml setting reaches it.
    """
    if not isinstance(report, GenerateReport) or report.untimely_attribute_option_combos is None:
        return
    summary = report.untimely_attribute_option_combos
    _hint(
        "warning",
        f"{summary.form_count} published form(s) declare attribute option combos DHIS2 has closed: no attribute "
        f"option combo of the form is valid for any period it reports, so no capture for one of them can be "
        f"keyed to a combo this DHIS2 instance accepts, and the facade refuses to draft a response for one. "
        f"They are: {', '.join(summary.forms)}. {UNTIMELY_ATTRIBUTE_OPTION_COMBO_REMEDY}",
        style="yellow",
    )


def _render_computed_questions(report: GenerateReport | LoadSetReport) -> None:
    """Say out loud that a form's examples leave a question empty because DHIS2 computes the answer.

    Its own line at the end of the run, for the reason the dead-form warnings have one: the examples
    this run wrote answer fewer questions than the form asks, on purpose, and the only other place
    that is said is one note among the several hundred a national instance raises. A reader watching
    a form publish nine answers to thirteen questions otherwise has nothing to tell a deliberate gap
    from a broken emitter.

    The line names the forms, the way the combo warnings do: a count alone sends a reader to the
    notes file for the one fact that decides what to do next.
    """
    if not isinstance(report, GenerateReport) or report.computed_questions is None:
        return
    summary = report.computed_questions
    _hint(
        "note",
        f"{summary.form_count} published form(s) ask {summary.question_count} question(s) a DHIS2 program rule "
        "computes the answer to on import, so every example this run wrote leaves them unanswered - DHIS2 "
        "refuses a capture answering one anything but the value it calculated, with E1307. "
        f"They are: {', '.join(summary.forms)}.",
    )


def _render_selection_mismatches(outcomes: list[_TargetOutcome]) -> None:
    """Say out loud that a `[generate.*] include_ids` entry named something the instance does not hold.

    Its own line at the end of the run, for the reason the empty-assignment warning has one: a UID
    that matched nothing costs a whole form, its examples and its pages, and the run that lost them
    otherwise reports the loss as one note among the several hundred a national instance raises.
    A guide is regenerated against an instance that has moved on, so this is how a reader learns
    that a data set was renamed out from under the selection rather than that the guide shrank.
    """
    for note in {note.message: note for outcome in outcomes for note in outcome.report.notes}.values():
        if note.category is GenerateNoteCategory.SELECTION_MISMATCH:
            _hint("warning", note.message, style="yellow")


def _full_outcomes(report: GenerateFullReport) -> list[_TargetOutcome]:
    """Every target the full run wrote, in the order it wrote them - three for a registry package, seven for a guide."""
    targets = (
        ("foundation", report.foundation),
        ("option-sets", report.option_sets),
        ("categories", report.categories),
        ("questionnaires", report.questionnaires),
        ("examples", report.examples),
        ("org-units", report.organisation_units),
        ("pages", report.pages),
    )
    return [
        _TargetOutcome(target=name, report=target_report) for name, target_report in targets if target_report.applies
    ]


def _full_run_summary(report: GenerateFullReport) -> str:
    """The closing line of a full run: how much it wrote, across how many targets."""
    outcomes = _full_outcomes(report)
    written = sum(len(outcome.report.written_files) for outcome in outcomes)
    return f"full pipeline: {written:,} file(s) written across {len(outcomes)} target(s)"


#: The basename the notes of one full run are written under, inside the reports directory.
_GENERATE_NOTES_STEM = "fhir-generate-notes"

#: The heading the notes that only restate a `d2w fhir validate` finding are filed under, per target.
_ECHO_SECTION_HEADING = "Restatements of validate findings"


def _plain_notes(outcome: _TargetOutcome) -> list[GenerateNote]:
    """The notes of one target that say something `d2w fhir validate` does not already say better."""
    return [note for note in outcome.report.notes if not note.echoes_validate]


def _echo_notes(outcome: _TargetOutcome) -> list[GenerateNote]:
    """The notes of one target that only restate a finding the validate report carries in full."""
    return [note for note in outcome.report.notes if note.echoes_validate]


def _write_generate_notes(
    outcomes: Iterable[_TargetOutcome], generation: GenerationProfile, project_root: Path
) -> Path:
    """Write every note of one full run to `reports/fhir-generate-notes.md`, grouped by target.

    Each note appears once, under the first target that raised it - the outcomes arrive on the
    run's distinct-notes view. A target's own notes come first; the ones that only restate a
    `d2w fhir validate` finding follow in a trailing subsection, so the file still holds
    everything the run raised while reading as what generation alone has to say.
    """
    from datetime import UTC, datetime

    from dhis2w_fhir import REPORTS_DIRECTORY

    directory = project_root / REPORTS_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        "# fhir generate notes",
        "",
        f"- Profile: {generation.name} ({generation.profile.base_url})",
        f"- Generated: {datetime.now(tz=UTC).isoformat(timespec='seconds')}",
        "",
    ]
    for outcome in outcomes:
        if not outcome.report.notes:
            continue
        lines.append(f"## {outcome.target}")
        lines.append("")
        lines.extend(f"- {note.message}" for note in _plain_notes(outcome))
        lines.append("")
        echoes = _echo_notes(outcome)
        if echoes:
            lines.append(f"### {_ECHO_SECTION_HEADING}")
            lines.append("")
            lines.extend(f"- {note.message}" for note in echoes)
            lines.append("")
    destination = directory / f"{_GENERATE_NOTES_STEM}.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def _generate_notes_hint(outcomes: list[_TargetOutcome], destination: Path) -> str:
    """The one line a bare run carries its notes on: what generation raised, then the validate echoes.

    The counts are distinct notes, which is what the summary table's own column counts: a note two
    targets raise about the same object is one note here and one row in the report file, while each
    target's `[k/N]` step line counts its own share of it.
    """
    plain_targets = [outcome for outcome in outcomes if _plain_notes(outcome)]
    plain_total = sum(len(_plain_notes(outcome)) for outcome in plain_targets)
    echo_total = sum(len(_echo_notes(outcome)) for outcome in outcomes)
    tail = f"; full list in {destination} (--details to print)"
    if not plain_total:
        echo_targets = sum(1 for outcome in outcomes if _echo_notes(outcome))
        return f"{echo_total} distinct validate echo(es) across {echo_targets} target(s){tail}"
    echoes = f" (+{echo_total} validate echoes)" if echo_total else ""
    return f"{plain_total} distinct note(s) across {len(plain_targets)} target(s){echoes}{tail}"


def _render_full_notes(outcomes: list[_TargetOutcome], generation: GenerationProfile, *, details: bool) -> None:
    """Say where the run's notes are, or print them all when the caller asked to read them here.

    A national instance raises several aggregate notes per target, and eight targets of them bury
    the summary table the run is actually read from. The count and the file are what the terminal
    carries; `--details` is the firehose.

    The count is of what generation alone found. A note that only restates a `d2w fhir validate`
    finding - a code fall-back, a code collision, a stem fall-back - is counted separately at the end
    of the line, because the validate report says the same thing about the same objects at length.
    """
    noted = [outcome for outcome in outcomes if outcome.report.notes]
    if not noted:
        return
    if details:
        for outcome in noted:
            for note in outcome.report.notes:
                _hint("note", f"{outcome.target}: {note.message}")
        return
    destination = _write_generate_notes(noted, generation, outcomes[0].report.project_root)
    _hint("note", _generate_notes_hint(noted, destination))


def _render_full_report(report: GenerateFullReport, generation: GenerationProfile, *, details: bool = False) -> None:
    """Render a full run as one row per target, then say where the notes the run raised are.

    Subject and the file columns are two different numbers: the subject names what the target
    covers in the instance's own objects, and the file counts say how many files that took, which
    is larger wherever one covered object ships as several resources.

    Rendering reads the distinct-notes view of the run, so a note several targets share is
    counted and printed once, on the first target that raised it; the `--json` dump keeps the
    full per-target lists, which read exactly as the solo commands' do. That is also why the
    `Distinct notes` column and a target's own `[k/N]` step line carry different numbers: the
    step line counts what that target raised, the column counts it once for the whole run.
    """
    outcomes = _full_outcomes(report.with_distinct_notes())
    rows = [
        {
            "target": outcome.target,
            "subject": outcome.report.subject.label() if outcome.report.subject is not None else "",
            "directory": _target_label(outcome.report),
            "written": f"{len(outcome.report.written_files):,}",
            "unchanged": f"{outcome.report.unchanged_count:,}",
            "deleted": f"{len(outcome.report.deleted_files):,}",
            "notes": f"{len(outcome.report.notes):,}",
        }
        for outcome in outcomes
    ]
    _hint("info", f"{generation.name} ({generation.origin}) -> {report.foundation.project_root}")
    render_list("fhir generate", rows, _fitted_columns(rows, STDERR_CONSOLE.width), console=STDERR_CONSOLE)
    _render_note_count_split(report, outcomes)
    _render_full_notes(outcomes, generation, details=details)
    _render_empty_assignments(report.questionnaires)
    _render_unusable_attribute_option_combos(report.questionnaires)
    _render_untimely_attribute_option_combos(report.questionnaires)
    _render_computed_questions(report.questionnaires)
    _render_selection_mismatches(outcomes)


def _render_note_count_split(report: GenerateFullReport, outcomes: list[_TargetOutcome]) -> None:
    """Name the run's two note counts when they differ, so the screen does not read as a contradiction.

    A target announcing `329 notes raised here` beside a `Distinct notes` column reading 0 states one
    fact twice under two countings, and nothing on screen says which is which. The sentence is
    printed under the table it explains, and only when the two numbers really do disagree.
    """
    raised = sum(len(outcome.report.notes) for outcome in _full_outcomes(report))
    distinct = sum(len(outcome.report.notes) for outcome in outcomes)
    if raised == distinct:
        return
    _hint(
        "note",
        f"the run's step lines count {raised:,} note(s) and the table counts {distinct:,}: a step line "
        "counts what that target raised, and the Distinct notes column counts a note once for the whole "
        "run, on the first target that raised it",
    )


#: The generate summary's columns, in the order they are rendered. The two prose columns carry a
#: floor and an ellipsis, so a terminal too narrow for them shortens what they say instead of
#: rendering two blank characters; the counting columns wrap their heading rather than lose a digit.
_FULL_REPORT_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("Target", "target", no_wrap=True),
    ColumnSpec("Subject", "subject", overflow="ellipsis", min_width=12),
    ColumnSpec("Directory", "directory", overflow="ellipsis", min_width=12),
    ColumnSpec("Files written", "written"),
    ColumnSpec("Files unchanged", "unchanged"),
    ColumnSpec("Files deleted", "deleted"),
    ColumnSpec("Distinct notes", "notes"),
]

#: The columns a narrow terminal loses, in the order they go. Each one's number is on the target's
#: own `[k/N]` step line and in the `--json` dump, so what a narrow table drops is said elsewhere;
#: what is left is the four a reader identifies a target and its cost by.
_DROPPED_WHEN_NARROW = ("unchanged", "deleted", "directory")


def _fitted_columns(rows: list[dict[str, str]], width: int) -> list[ColumnSpec]:
    """The widest column set that fits the terminal, dropping the recoverable ones until it does."""
    columns = list(_FULL_REPORT_COLUMNS)
    for key in _DROPPED_WHEN_NARROW:
        if _table_width(columns, rows) <= width:
            break
        columns = [column for column in columns if column.key != key]
    return columns


#: What a column a cell may be cut in is measured at, however long its longest cell runs. A column
#: that ends in an ellipsis still reads as itself, so it is not what a narrow table has to give up.
_CUTTABLE_COLUMN_WIDTH = 20


def _table_width(columns: list[ColumnSpec], rows: list[dict[str, str]]) -> int:
    """How wide the table asks to be: every cell plus the frame, with a cuttable column at its cut width.

    The frame is what Rich draws around the cells: one vertical per column plus one to close the row,
    and a space either side of every cell. A cuttable column asks for its cut width or its own floor,
    whichever is larger, because a floor is what the renderer will not go below however narrow the
    terminal is - a column counted under its floor is a table that overflows the screen it fit on
    paper.
    """
    content = 0
    for column in columns:
        natural = max([len(column.label), *(len(row[column.key]) for row in rows)])
        if column.overflow == "ellipsis":
            content += max(column.min_width or 0, min(natural, _CUTTABLE_COLUMN_WIDTH))
        else:
            content += natural
    return content + 3 * len(columns) + 1


@generate_app.callback(invoke_without_command=True)
def generate_callback(
    ctx: typer.Context,
    details: Annotated[
        bool,
        typer.Option("--details", help="Print every note inline instead of writing them to the notes report."),
    ] = False,
    substitute_hostile_names: Annotated[
        bool,
        typer.Option(
            "--substitute-hostile-names",
            help="Publish a DHIS2 name carrying '<' in rewritten wording (\"5 to < 15 years\" becomes "
            '"5 to under 15 years") and a DHIS2 code carrying a space with the space hyphenated '
            '("Pre eclampsia" becomes "Pre-eclampsia"), instead of being asked. DHIS2 is never '
            "modified, and each rewritten concept states its DHIS2 code as a `dhis2-code` property.",
        ),
    ] = False,
    refuse_hostile_names: Annotated[
        bool,
        typer.Option(
            "--refuse-hostile-names",
            help="Refuse the run over a DHIS2 name carrying '<' instead of being asked, so the name is "
            "changed in DHIS2 before a build is spent on it. Every code is published byte-true.",
        ),
    ] = False,
    progress: ProgressOption = True,
) -> None:
    """Generate the whole IG source from DHIS2 metadata, or one named target of it.

    Bare `d2w fhir generate` runs every target off a single pass over the instance.

    The foundation runs first because it reads nothing, the pages last because they narrate the rest.

    Notes land in reports/fhir-generate-notes.md; `--details` prints them here instead.

    Name a target to run that one alone; --details and --progress belong to the bare run, and the
    two hostile-name flags belong to every target under this group.
    """
    ctx.obj = GenerateDecisions(
        hostile_names=_hostile_name_posture(substitute=substitute_hostile_names, refuse=refuse_hostile_names)
    )
    if ctx.invoked_subcommand is not None:
        return
    from dhis2w_fhir import service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    gate = _hostile_name_gate(ctx, project)
    with _progress(service.generate_full_steps(project), enabled=progress) as reporter:
        report = asyncio.run(service.generate_full(generation.profile, project, reporter=reporter, gate=gate))
        if reporter is not None:
            reporter.finish(_full_run_summary(report))
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_full_report(report, generation, details=details)


@generate_app.command("foundation")
def generate_foundation_command(progress: ProgressOption = True) -> None:
    """Generate the DHIS2 identifier aliases, the extensions, and the capture contract into the FHIR project."""
    from dhis2w_fhir import GENERATE_FOUNDATION_STEPS, service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    with _progress(GENERATE_FOUNDATION_STEPS, enabled=progress) as reporter:
        report = asyncio.run(service.generate_foundation(project, reporter=reporter))
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_generate_report(_TARGET_TITLES["foundation"], report, generation)


@generate_app.command("option-sets")
def generate_option_sets_command(ctx: typer.Context, progress: ProgressOption = True) -> None:
    """Generate CodeSystem/ValueSet JSON from DHIS2 option sets into the nearest FHIR project."""
    from dhis2w_fhir import GENERATE_TARGET_STEPS, service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    gate = _hostile_name_gate(ctx, project)
    with _progress(GENERATE_TARGET_STEPS, enabled=progress) as reporter:
        report = asyncio.run(service.generate_option_sets(generation.profile, project, reporter=reporter, gate=gate))
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_generate_report(
        _TARGET_TITLES["option-sets"],
        report,
        generation,
        extra_rows=[DetailRow("option sets", f"{report.option_set_count:,}")],
    )


@generate_app.command("categories")
def generate_categories_command(ctx: typer.Context, progress: ProgressOption = True) -> None:
    """Generate CodeSystem/ValueSet JSON from DHIS2 categories into the nearest FHIR project."""
    from dhis2w_fhir import GENERATE_TARGET_STEPS, service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    gate = _hostile_name_gate(ctx, project)
    with _progress(GENERATE_TARGET_STEPS, enabled=progress) as reporter:
        report = asyncio.run(service.generate_categories(generation.profile, project, reporter=reporter, gate=gate))
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_generate_report(
        _TARGET_TITLES["categories"],
        report,
        generation,
        extra_rows=[DetailRow("categories", f"{report.category_count:,}")],
    )


@generate_app.command("questionnaires")
def generate_questionnaires_command(ctx: typer.Context, progress: ProgressOption = True) -> None:
    """Generate Questionnaire FSH into data-sets/, event-programs/, tracker-programs/, and data-dictionary/.

    A data set and an event program are one Questionnaire each.

    A tracker program is one Questionnaire per program stage, filed under its program's UID.

    A form whose DHIS2 organisation-unit assignment narrows the published registry also gets one
    List of the Locations it admits, into resources/assignments/.
    """
    from dhis2w_fhir import GENERATE_TARGET_STEPS, service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    gate = _hostile_name_gate(ctx, project)
    with _progress(GENERATE_TARGET_STEPS, enabled=progress) as reporter:
        report = asyncio.run(service.generate_questionnaires(generation.profile, project, reporter=reporter, gate=gate))
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_generate_report(
        _TARGET_TITLES["questionnaires"],
        report,
        generation,
        extra_rows=[
            DetailRow("questionnaires", f"{report.questionnaire_count:,}"),
            DetailRow("assignments", f"{report.assignment_count:,}"),
        ],
    )


@generate_app.command("examples")
def generate_examples_command(ctx: typer.Context, progress: ProgressOption = True) -> None:
    """Generate example QuestionnaireResponses for every configured data set, event program, and tracker stage."""
    from dhis2w_fhir import GENERATE_TARGET_STEPS, service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    gate = _hostile_name_gate(ctx, project)
    with _progress(GENERATE_TARGET_STEPS, enabled=progress) as reporter:
        report = asyncio.run(service.generate_examples(generation.profile, project, reporter=reporter, gate=gate))
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_generate_report(
        _TARGET_TITLES["examples"],
        report,
        generation,
        extra_rows=[DetailRow("examples", f"{report.example_count:,}")],
    )


@generate_app.command("org-units")
def generate_organisation_units_command(ctx: typer.Context, progress: ProgressOption = True) -> None:
    """Generate Organization/Location FSH from DHIS2 organisation units into the nearest FHIR project."""
    from dhis2w_fhir import GENERATE_TARGET_STEPS, service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    gate = _hostile_name_gate(ctx, project)
    with _progress(GENERATE_TARGET_STEPS, enabled=progress) as reporter:
        report = asyncio.run(
            service.generate_organisation_units(generation.profile, project, reporter=reporter, gate=gate)
        )
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_generate_report(
        _TARGET_TITLES["org-units"],
        report,
        generation,
        extra_rows=[
            DetailRow("organisation units", f"{report.organisation_unit_count:,}"),
            DetailRow("positions", f"{report.position_count:,}"),
            DetailRow("boundaries", f"{report.boundary_count:,}"),
        ],
    )


@generate_app.command("pages")
def generate_pages_command(ctx: typer.Context, progress: ProgressOption = True) -> None:
    """Generate the narrative site pages and the per-artifact intros into ig/input/pagecontent/."""
    from dhis2w_fhir import GENERATE_TARGET_STEPS, service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    gate = _hostile_name_gate(ctx, project)
    with _progress(GENERATE_TARGET_STEPS, enabled=progress) as reporter:
        report = asyncio.run(service.generate_pages(generation.profile, project, reporter=reporter, gate=gate))
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_generate_report(
        _TARGET_TITLES["pages"],
        report,
        generation,
        extra_rows=[DetailRow("pages", f"{report.page_count:,}"), DetailRow("intros", f"{report.intro_count:,}")],
    )


@generate_app.command("load-set")
def generate_load_set_command(
    per_target: Annotated[
        int,
        typer.Option(
            "--per-target",
            min=1,
            help="How many synthetic responses each questionnaire target contributes.",
        ),
    ] = DEFAULT_LOAD_SET_PER_TARGET,
    salt: Annotated[
        str,
        typer.Option(
            "--salt",
            help="Mint a different corpus from the same metadata - name any string to move every drawn value.",
        ),
    ] = "",
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            file_okay=False,
            help="Directory to write the `load/` corpus into (default: the project root).",
        ),
    ] = None,
    progress: ProgressOption = True,
) -> None:
    """Write a synthetic QuestionnaireResponse corpus into load/ for posting at a running `d2w fhir serve`.

    A load set is test data, not IG source: it lands beside `ig/` rather than inside it.

    The scaffold gitignores it, and `d2w fhir generate` never writes it.

    A corpus mints the DHIS2 identities it names, so it imports once: DHIS2 refuses a second import
    of the same corpus with E1002 and E1080 because those UIDs already exist. Pass `--salt` to mint
    a fresh corpus for a second import; the same salt reproduces the same corpus.
    """
    from dhis2w_fhir import GENERATE_TARGET_STEPS, service

    project = load_project()
    generation = service.resolve_generation_profile(project)
    with _progress(GENERATE_TARGET_STEPS, enabled=progress) as reporter:
        report = asyncio.run(
            service.generate_load_set(
                generation.profile,
                project,
                per_target=per_target,
                salt=salt,
                output_directory=output_dir,
                reporter=reporter,
            )
        )
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_generate_report(
        _TARGET_TITLES["load-set"],
        report,
        generation,
        extra_rows=[
            DetailRow("responses", f"{report.response_count:,}"),
            DetailRow("questionnaires", f"{report.questionnaire_count:,}"),
        ],
    )


def _parse_report_formats(value: str) -> list[str]:
    """Parse the `--format` comma list into the canonical write order, rejecting unknown names."""
    requested = {item.strip().lower() for item in value.split(",") if item.strip()}
    unknown = sorted(requested - set(_REPORT_FORMATS))
    if unknown:
        raise typer.BadParameter(f"unknown format(s): {', '.join(unknown)} (choose from md, csv, pdf)")
    if not requested:
        raise typer.BadParameter("at least one format is required (choose from md, csv, pdf)")
    return [name for name in _REPORT_FORMATS if name in requested]


@app.command("validate")
def validate_command(
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            file_okay=False,
            help="Directory to write the report files into, one per format, all named "
            "fhir-validate-report (default: reports/ under the project root, else the working directory).",
        ),
    ] = None,
    formats: Annotated[
        str, typer.Option("--format", help="Comma-separated report formats to write: md, csv, pdf.")
    ] = "md,csv,pdf",
    code_source: Annotated[
        CodeSourceChoice | None,
        typer.Option(
            "--code-source",
            help="Override `\\[generate]` concept_code_source for this run. In id mode the option code "
            "findings are informational; run with code to see what switching would cost.",
        ),
    ] = None,
    hostile_names: Annotated[
        HostileNamePosture | None,
        typer.Option(
            "--hostile-names",
            help="Override `\\[generate]` hostile_names for this run. Under substitute a name carrying '<' "
            "is rewritten for publication, so the findings on those names are graded informational; "
            "under refuse they abort the build and stay errors.",
        ),
    ] = None,
    details: Annotated[
        bool,
        typer.Option("--details", help="List every finding individually instead of the rolled-up category counts."),
    ] = False,
    fail: Annotated[bool, typer.Option("--fail/--no-fail", help="Exit 1 when errors are found.")] = True,
    progress: ProgressOption = True,
) -> None:
    r"""Check the instance's codes for FHIR-safety, writing md/csv/pdf reports grouped by type.

    Severity means build impact on the configured IG: an error aborts your build (generate refuses
    the same codes), a warning degrades an emitted resource, and an info is instance hygiene on
    objects the build never reads. Each finding carries that verdict as its scope - `selection`
    for objects the configured selection emits, `instance` for the rest.

    The run grades under the project's `\[generate] hostile_names` posture, and the summary states
    which one it read. Under `substitute` a DHIS2 name carrying '<' is rewritten for publication
    and the build survives it, so the finding on that name is informational and says what the guide
    publishes; under `refuse` - and unset, which refuses - the same name aborts the build and stays
    an error. A DHIS2 code carrying '<' is an error under either posture: the substitution rewrites
    a space in a code and never a '<'.

    The terminal says what the state is: a summary, a count per severity, scope, and category, and
    every error by name, because an error is what gates the build and the user has to know which
    object holds it. The written report is where a warning is read one row at a time; `--details`
    puts every row on the terminal too.
    """
    from datetime import UTC, datetime

    from dhis2w_fhir import REPORTS_DIRECTORY, VALIDATE_CODES_STEPS, find_project_fhir_config, service
    from dhis2w_fhir.notes import pluralize
    from dhis2w_fhir.validation.pdf import render_validation_pdf
    from dhis2w_fhir.validation.report import render_validation_csv, render_validation_markdown

    selected_formats = _parse_report_formats(formats)
    requested_source = code_source.value if code_source is not None else None
    context = service.resolve_validation_context()
    with _progress(VALIDATE_CODES_STEPS, enabled=progress) as reporter:
        report = asyncio.run(
            service.validate_codes(
                context.generation.profile,
                context.config,
                requested_source,
                hostile_names,
                publishes_forms=context.publishes_forms,
                reporter=reporter,
            )
        )
    project_config = find_project_fhir_config()
    default_root = project_config.parent if project_config else Path.cwd()
    directory = output_dir or default_root / REPORTS_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    target = f"{context.generation.name} ({context.generation.profile.base_url})"
    generated_at = datetime.now(tz=UTC)
    for report_format in selected_formats:
        destination = directory / f"{_VALIDATION_REPORT_STEM}.{report_format}"
        if report_format == "md":
            destination.write_text(render_validation_markdown(report, target, generated_at), encoding="utf-8")
        elif report_format == "csv":
            destination.write_text(render_validation_csv(report), encoding="utf-8")
        else:
            destination.write_bytes(render_validation_pdf(report, target, generated_at))
        _line(f"wrote {destination}")
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
    else:
        summary_rows = [
            DetailRow("profile", f"{context.generation.name} ({context.generation.origin})"),
            DetailRow("resource types", str(report.resource_type_count)),
            DetailRow("objects swept", str(report.object_count)),
            DetailRow("option sets", str(report.option_set_count)),
            DetailRow("options", str(report.option_count)),
            DetailRow("attributes", str(report.attribute_count)),
            DetailRow("errors", str(report.error_count)),
            DetailRow("warnings", str(report.warning_count)),
            DetailRow("infos", str(report.info_count)),
        ]
        if report.code_coverage is not None:
            summary_rows.extend(
                [
                    DetailRow(
                        "selection findings",
                        f"{pluralize(report.selection_error_count, 'error')}, "
                        f"{pluralize(report.selection_warning_count, 'warning')}, "
                        f"{pluralize(report.selection_info_count, 'info')}",
                    ),
                    DetailRow(
                        "code coverage",
                        f"{report.code_coverage.line} (selection objects whose code can serve as an identity stem)",
                    ),
                ]
            )
        summary_rows.append(DetailRow("scope", _literal_cell(report.scope_line)))
        # Labelled by the key it is, not by what it is about: the row sits under a `code coverage`
        # row and beside `code-stem-refusal` findings, and those are `[generate.naming] source`.
        summary_rows.append(
            DetailRow(
                _literal_cell("[generate] concept_code_source"),
                service.resolve_code_source(context.config, requested_source),
            )
        )
        # Its sibling, beside it rather than inferred: the two decide different things and this table
        # is where a reader works out which of them a code finding is about.
        summary_rows.append(DetailRow(_literal_cell("[generate.naming] source"), str(context.config.naming.source)))
        summary_rows.append(DetailRow("hostile names", report.hostile_names_line))
        render_detail("fhir validate", summary_rows, console=STDERR_CONSOLE)
        if report.not_applicable_surfaces:
            _hint(
                "note",
                f"not applicable: {', '.join(report.not_applicable_surfaces)} - this project publishes none of "
                "them, so what the instance holds of each is hygiene rather than this build's problem",
            )
        _render_finding_rollup(report)
        listed = [finding for finding in report.findings if details or finding.severity == "error"]
        if listed:
            rows = _finding_rows(listed, STDERR_CONSOLE.width)
            columns = _fitted_finding_columns(rows, STDERR_CONSOLE.width)
            render_list(
                "findings",
                _sentences_fitted(rows, columns, STDERR_CONSOLE.width),
                columns,
                console=STDERR_CONSOLE,
            )
        if not report.error_count:
            _hint("ok", f"{_passed_summary(report)}; full findings in {directory / f'{_VALIDATION_REPORT_STEM}.md'}")
    if report.error_count and fail:
        _hint("error", f"{report.error_count} error(s) found; exiting 1 (--no-fail to suppress)", style="red")
        raise typer.Exit(code=1)


#: The severity order the rollup reads in - what blocks a build first, what only reads badly last.
_SEVERITY_ORDER = ("error", "warning", "info")

#: The scope order within one severity - the build path before the instance hygiene.
_SCOPE_ORDER = ("selection", "instance")

#: The style each severity carries in the rollup, so a glance separates a blocker from a note.
_SEVERITY_STYLES = {"error": "red", "warning": "yellow", "info": "dim"}


def _severity_cell(value: Any) -> str:
    """Render one severity in the style it carries, so the blockers read as blockers."""
    severity = str(value)
    return f"[{_SEVERITY_STYLES.get(severity, 'default')}]{severity}[/]"


def _scope_cell(value: Any) -> str:
    """Render one scope: selection full-strength, instance dimmed, so the build path carries the weight."""
    scope = str(value)
    return f"[dim]{scope}[/]" if scope == "instance" else scope


#: How many characters of a finding's sentence the terminal carries at its widest, and the fewest
#: worth printing at all. The whole of it is in the markdown and csv reports the run writes; on
#: screen it is what tells one row's fault from the next, and a cell left unbounded takes every
#: other column's width with it however wide the screen is. Between the two the sentence takes
#: whatever the terminal has left once every other column has what it needs, which is what makes it
#: the cell a narrow screen shortens.
_FINDING_MESSAGE_WIDTH = 60
_FINDING_MESSAGE_FLOOR = 24

#: What one DHIS2 code carries on screen. A code is a short identifier by design, and one long
#: enough to matter is in the reports and in `--json` - so the column is bounded rather than left to
#: take the sentence's room.
_FINDING_CODE_WIDTH = 20

#: What the two columns the fit is worked around are headed, named once because it measures their
#: headings as well as their cells.
_OBJECT_COLUMN_LABEL = "Object"
_MESSAGE_COLUMN_LABEL = "Why it matters"

#: How long a DHIS2 UID is, and the three characters an Object cell spends parenthesising one.
_UID_WIDTH = 11
_PARENTHESISED_UID_WIDTH = len(" ()") + _UID_WIDTH

#: The narrowest an Object cell is ever cut to: a DHIS2 name of `_FINDING_NAME_FLOOR` characters and
#: the whole parenthesised UID behind it. A cell is cut on its name, never on its UID - the UID is
#: what a reader greps the report files for and what every remedy is typed against, and a name is
#: recognisable long before it is complete.
_FINDING_NAME_FLOOR = 20
_FINDING_OBJECT_WIDTH = _FINDING_NAME_FLOOR + _PARENTHESISED_UID_WIDTH

#: The terminal the floors are set for: 80 columns is what a pipe gets, and the width at which the
#: table has already given up every column it can. A wider screen spends a quarter of what it adds
#: on the name, which is what a reader identifies a row by after its UID.
_NARROW_TERMINAL_WIDTH = 80

#: The findings table's columns, in the order they are rendered. Every cell is cut to what this
#: terminal carries before the table is built, so the table asks for no more room than the screen
#: has and every column renders at the width its own cells need: nothing folds down the page, and no
#: column is squeezed to the blank stub an 11-character UID rendered one character to a line would
#: be. The floors are what each column keeps when the fit is tight.
_FINDING_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("Severity", "severity", formatter=_severity_cell, no_wrap=True, min_width=8),
    ColumnSpec("Scope", "scope", formatter=_scope_cell, no_wrap=True, min_width=5),
    ColumnSpec("Category", "category", no_wrap=True, min_width=8),
    ColumnSpec("Type", "type", no_wrap=True, min_width=4),
    ColumnSpec(_OBJECT_COLUMN_LABEL, "object", no_wrap=True, overflow="ellipsis"),
    ColumnSpec("Code", "code", no_wrap=True, overflow="ellipsis", min_width=8),
    ColumnSpec(_MESSAGE_COLUMN_LABEL, "message", no_wrap=True, overflow="ellipsis", min_width=_FINDING_MESSAGE_FLOOR),
]


#: The finding columns a narrow terminal loses, in the order they go. The scope and the category of
#: every finding are counted in the `findings by category` table printed above this one, and every
#: one of the four is in the report files and in `--json`, so what a narrow table drops is said
#: elsewhere. The code goes last of the four and only where the object and the sentence cannot both
#: stand beside it: what a reader acts on first is how bad it is, which object, and why. 80 columns
#: is what a pipe gets.
_DROPPED_FINDING_COLUMNS_WHEN_NARROW = ("scope", "category", "type", "code")


def _finding_rows(findings: list[ValidationFinding], width: int) -> list[dict[str, str]]:
    """One table row per finding, every cell already cut to what a terminal of `width` carries."""
    from dhis2w_fhir.validation.report import display_code

    return [
        {
            "severity": finding.severity,
            "scope": finding.scope,
            "category": finding.category,
            "type": finding.resource_type,
            "object": _finding_object_cell(finding.name, finding.uid, width),
            "code": _truncate(display_code(finding.code), _FINDING_CODE_WIDTH),
            "message": _truncate(finding.message, _FINDING_MESSAGE_WIDTH),
        }
        for finding in findings
    ]


def _fitted_finding_columns(rows: list[dict[str, str]], width: int) -> list[ColumnSpec]:
    """The widest finding column set that fits the terminal, dropping the recoverable ones until it does.

    Measured with the sentence at its floor, because the sentence is what takes whatever the other
    columns leave: a set is kept as soon as every other column's own cells fit beside a readable
    fragment of it.
    """
    columns = list(_FINDING_COLUMNS)
    for key in _DROPPED_FINDING_COLUMNS_WHEN_NARROW:
        if _finding_table_width(columns, rows) <= width:
            break
        columns = [column for column in columns if column.key != key]
    return columns


def _sentences_fitted(rows: list[dict[str, str]], columns: list[ColumnSpec], width: int) -> list[dict[str, str]]:
    """The same rows with each sentence cut to the room the other columns leave it on this terminal."""
    if not any(column.key == "message" for column in columns):
        return rows
    taken = sum(_finding_column_width(column, rows) for column in columns if column.key != "message")
    room = width - taken - _finding_frame_width(columns)
    sentence = max(_FINDING_MESSAGE_FLOOR, min(_FINDING_MESSAGE_WIDTH, room))
    return [{**row, "message": _truncate(row["message"], sentence)} for row in rows]


def _finding_table_width(columns: list[ColumnSpec], rows: list[dict[str, str]]) -> int:
    """How wide the findings table asks to be: every cell at its own width, the sentence at its floor."""
    content = sum(
        _FINDING_MESSAGE_FLOOR if column.key == "message" else _finding_column_width(column, rows) for column in columns
    )
    return content + _finding_frame_width(columns)


def _finding_column_width(column: ColumnSpec, rows: list[dict[str, str]]) -> int:
    """How wide one column's own content runs: its heading, or its longest cell where that is longer."""
    return max([len(column.label), *(len(row[column.key]) for row in rows)])


def _finding_frame_width(columns: list[ColumnSpec]) -> int:
    """What Rich draws around the cells: one vertical per column plus one closing the row, and a space either side."""
    return 3 * len(columns) + 1


def _finding_object_cell(name: str, uid: str, width: int) -> str:
    """One Object cell cut so the UID survives: the name gives way to a narrow terminal, the UID never does."""
    return f"{_truncate(name, _finding_object_width(width) - _PARENTHESISED_UID_WIDTH)} ({uid})"


def _finding_object_width(width: int) -> int:
    """How much of one Object cell a terminal of `width` carries: the floor, plus a share of what it adds."""
    return _FINDING_OBJECT_WIDTH + max(0, width - _NARROW_TERMINAL_WIDTH) // 4


def _instance_dimmed(text: str, scope: str) -> str:
    """Dim one rollup cell on an instance row, so out-of-scope hygiene reads as background."""
    return f"[dim]{text}[/]" if scope == "instance" else text


def _passed_summary(report: FhirValidationReport) -> str:
    """The passing line's counts: split by scope when one was resolved, plain totals otherwise."""
    if report.code_coverage is None:
        return f"passed: {report.warning_count} warning(s), {report.info_count} info(s)"
    instance_count = sum(1 for finding in report.findings if finding.scope == "instance")
    return (
        f"passed: {report.selection_warning_count} selection warning(s), "
        f"{report.selection_info_count} selection info(s), {instance_count} instance finding(s)"
    )


def _render_finding_rollup(report: FhirValidationReport) -> None:
    """Render one row per (severity, scope, category) with its count - the whole report at a glance."""
    counts = Counter((finding.severity, finding.scope, finding.category) for finding in report.findings)
    if not counts:
        return
    ordered = sorted(counts, key=lambda key: (_SEVERITY_ORDER.index(key[0]), _SCOPE_ORDER.index(key[1]), key[2]))
    render_list(
        "findings by category",
        [
            {
                "severity": severity,
                "scope": _scope_cell(scope),
                "category": _instance_dimmed(category, scope),
                "count": _instance_dimmed(str(counts[severity, scope, category]), scope),
            }
            for severity, scope, category in ordered
        ],
        [
            ColumnSpec("Severity", "severity", formatter=_severity_cell, no_wrap=True),
            ColumnSpec("Scope", "scope", no_wrap=True),
            ColumnSpec("Category", "category", no_wrap=True),
            ColumnSpec("Count", "count", no_wrap=True),
        ],
        console=STDERR_CONSOLE,
    )


#: How many characters of an offending value the terminal carries before it is cut. A DHIS2 name is
#: short; a narrative-bound string is not, and one runaway row must not push the remedy off screen.
_ARTIFACT_VALUE_WIDTH = 60

#: How many characters of a file path the terminal carries, and the floor its column keeps. A
#: compiled artifact sits four directories down under a name the resource id already states, so the
#: path is cut from the front - what names the file is its end - and the cell is then never cut a
#: second time from the other end, which would leave four directory names and no file.
_ARTIFACT_FILE_WIDTH = 24


def _literal_cell(value: object) -> str:
    """One table cell rendered as the text it is, rather than as the Rich markup it may look like.

    These cells carry strings nobody wrote for a terminal: a DHIS2 name, a file path, and a line
    naming a `fhir.toml` table. Rich reads `[ig]` as a style tag and prints nothing where the table
    name should be, so a cell that can hold one states its own brackets.
    """
    from rich.markup import escape

    return escape(str(value))


#: The artifact findings table's columns, in the order they are rendered. The path and the offending
#: value carry a floor and an ellipsis, so a terminal too narrow shortens each cell instead of
#: folding it into a column of word fragments.
#:
#: The remedy is not a column. Six sentences stand behind every finding this scan raises, so a
#: column would print one of the six once per row - the same fact forty times, in the widest cell on
#: screen, starving every column a reader identifies the row by. They are printed under the table
#: instead, once each and whole, which is also the only place the `[generate.*]` table names inside
#: them survive a narrow screen.
_ARTIFACT_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("Severity", "severity", no_wrap=True),
    ColumnSpec(
        "File", "file", formatter=_literal_cell, no_wrap=True, overflow="ellipsis", min_width=_ARTIFACT_FILE_WIDTH
    ),
    ColumnSpec("Resource", "resource", no_wrap=True, formatter=_literal_cell),
    ColumnSpec("Field", "field", no_wrap=True, formatter=_literal_cell),
    ColumnSpec("Value", "value", formatter=_literal_cell, no_wrap=True, overflow="ellipsis", min_width=10),
]

#: The artifact columns a narrow terminal loses, in the order they go. The resource is named by the
#: file the row already carries and the element inside it is in `--json`, so what is left is what a
#: reader acts on: how bad it is, which file, and the offending string. 80 columns is what a CI log
#: gets, and `make build` runs this command into one.
_DROPPED_ARTIFACT_COLUMNS_WHEN_NARROW = ("resource", "field")


def _distinct(values: Iterable[str]) -> list[str]:
    """The given strings with repeats dropped, in the order they first appear."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def _fitted_artifact_columns(rows: list[dict[str, str]], width: int) -> list[ColumnSpec]:
    """The widest artifact column set that fits the terminal, dropping the recoverable ones until it does."""
    columns = list(_ARTIFACT_COLUMNS)
    for key in _DROPPED_ARTIFACT_COLUMNS_WHEN_NARROW:
        if _table_width(columns, rows) <= width:
            break
        columns = [column for column in columns if column.key != key]
    return columns


@app.command("check-artifacts")
def check_artifacts_command(
    directory: Annotated[
        Path | None,
        typer.Argument(
            file_okay=False,
            help="Project to scan (default: the nearest fhir.toml, walking up from the working directory).",
        ),
    ] = None,
    fail: Annotated[bool, typer.Option("--fail/--no-fail", help="Exit 1 when findings are found.")] = True,
    registry_package: Annotated[
        Path | None,
        typer.Option(
            "--registry-package",
            help="The organisation-unit registry package to check this guide's unit references against, "
            "when no `path` checkout answers. Only for a guide naming "
            "`\\[generate.organisation_units.registry]`.",
        ),
    ] = None,
) -> None:
    r"""Refuse the build before it begins: scan the artifacts on disk for what aborts the IG publisher.

    `d2w fhir generate` refuses a run whose selected DHIS2 names or codes carry a `<`. A build reads
    no such gate - it publishes whatever `ig/fsh-generated/` and `ig/input/` hold - so output written
    before the gate existed, output from an older pinned toolchain, and hand-authored FSH all reach
    the publisher, and cost its full run before failing in its final pass.

    This is that refusal applied to the files themselves, through the very predicates the generate
    gate uses, plus the guide's own identity in `fhir.toml` and `ig/sushi-config.yaml` - which no
    DHIS2 selection supplies and no compiled resource carries until SUSHI has run. It names the file,
    the resource, the element, and the value, so what comes back is the object rather than the page
    the publisher happened to die on, and the line that answers it follows from where the value came
    from rather than assuming DHIS2 wrote it.

    Two findings are warnings rather than refusals: a published form whose organisation-unit
    assignment names no organisation unit this project publishes, and a `\[generate.*] include_ids`
    entry this project publishes nothing carrying that UID for. That guide builds and publishes;
    what it costs is a form nobody can submit a response to, and a form the guide never carried.

    No connection, no profile, no compile - the artifacts are the whole input, so it answers in
    seconds. Exit 1 when anything build-aborting is found, which is what `make build` runs it for.
    """
    from dhis2w_fhir.validation.artifacts import check_publishable_artifacts

    project = load_project(directory)
    report = check_publishable_artifacts(project, registry_package=registry_package)
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        if report.build_aborting_count and fail:
            raise typer.Exit(code=1)
        return
    render_detail(
        "fhir check-artifacts",
        [
            DetailRow("project", str(project.project_root)),
            DetailRow("json files", str(report.json_file_count)),
            DetailRow("fsh files", str(report.fsh_file_count)),
            DetailRow("build-aborting", str(report.build_aborting_count)),
            DetailRow("warnings", str(report.warning_count)),
        ],
        console=STDERR_CONSOLE,
    )
    for unreadable in report.unreadable_files:
        _hint("note", f"{unreadable} is not readable as a JSON object; nothing in it was checked")
    if report.findings:
        rows = [
            {
                "severity": finding.severity,
                "file": _truncate_path(finding.file, _ARTIFACT_FILE_WIDTH),
                "resource": finding.resource_id,
                "field": finding.field,
                "value": _truncate(finding.value, _ARTIFACT_VALUE_WIDTH),
            }
            for finding in report.findings
        ]
        render_list(
            "artifact findings",
            rows,
            _fitted_artifact_columns(rows, STDERR_CONSOLE.width),
            console=STDERR_CONSOLE,
        )
        for remedy in _distinct(finding.remedy for finding in report.findings):
            _hint("note", f"what to do: {remedy}")
        for message in report.messages:
            _hint("note", f"what it costs: {message}")
    else:
        _hint("ok", f"{report.file_count} publishable file(s) scanned; nothing the IG publisher aborts on")
    if report.build_aborting_count and fail:
        _hint(
            "error",
            f"{report.build_aborting_count} build-aborting artifact(s) found; exiting 1 before the publisher runs "
            "(--no-fail to suppress)",
            style="red",
        )
        raise typer.Exit(code=1)
    if report.warning_count:
        _hint(
            "warning",
            f"{report.warning_count} finding(s) the build survives; the guide publishes and what it costs is "
            "read in the table above",
            style="yellow",
        )


#: What a caller is told when the serve extra is not installed, naming the command they actually
#: ran. `LookupError` renders through the CLI error funnel as a one-line message, which is what an
#: install instruction wants to be.
def _serve_package_missing(command: str) -> str:
    """The install instruction, under the name of the command that needed the package."""
    return (
        f"`d2w fhir {command}` needs the dhis2w-fhir-serve package. Install it with "
        "`uv add dhis2w-fhir-serve` or `pip install 'dhis2w-cli[serve]'`."
    )


class PortInUseError(LookupError):
    """A serve address something else already holds, rendered by the CLI error funnel as one line."""

    def __init__(self, *, host: str, port: int) -> None:
        """Carry the refusal naming the port, its usual holder, and both ways to move off it."""
        super().__init__(
            f"port {port} on {host} is already in use "
            "(usually the local DHIS2 instance; set [serve] port in fhir.toml or pass --port)"
        )


#: The wildcard of each IP stack, probed for every host. A server published to all interfaces -
#: which is what a Docker port mapping does, and how the local DHIS2 stack holds 8080 - listens on
#: one of these, and SO_REUSEADDR then lets a *loopback-specific* bind succeed underneath it. So a
#: probe of `127.0.0.1` alone reports a held port as free, uvicorn binds it just as happily, and
#: this server quietly takes the localhost traffic meant for the instance. Only the wildcard bind
#: collides with the wildcard listener, which is what makes the port's real holder visible.
_WILDCARD_ADDRESSES = (
    (socket.AF_INET, "0.0.0.0"),  # noqa: S104 - probed and released, never an address this serves on
    (socket.AF_INET6, "::"),
)

#: The other stack's loopback, for a host naming one. A listener can hold `::1` alone while nothing
#: holds `127.0.0.1`, and a browser asking this machine for `localhost` may still be routed to it.
_SIBLING_LOOPBACK_ADDRESSES = {
    "127.0.0.1": (socket.AF_INET6, "::1"),
    "::1": (socket.AF_INET, "127.0.0.1"),
    "localhost": (socket.AF_INET6, "::1"),
}

#: Bind failures that say this machine cannot offer the address at all - no IPv6 stack, or an
#: address belonging to some other host. Neither is the port being held by anything, so neither
#: refuses a run.
_ADDRESS_UNAVAILABLE_ERRNOS = frozenset({errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT})


def _probe_addresses(host: str, port: int) -> list[tuple[int, str]]:
    """Every (family, address) whose holder would contend for `host:port`, deduped in probe order."""
    candidates: list[tuple[int, str]] = []
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        # An unresolvable host is uvicorn's failure to report, not the preflight's: probe the
        # literal it was given and let the bind say what is wrong with it.
        resolved = []
    for family, _type, _protocol, _canonical_name, address in resolved:
        if family in (socket.AF_INET, socket.AF_INET6):
            candidates.append((family, str(address[0])))
    if not candidates:
        candidates.append((socket.AF_INET6 if ":" in host else socket.AF_INET, host))
    sibling = _SIBLING_LOOPBACK_ADDRESSES.get(host)
    if sibling is not None:
        candidates.append(sibling)
    candidates.extend(_WILDCARD_ADDRESSES)
    return list(dict.fromkeys(candidates))


def _bind_probe(host: str, port: int) -> None:
    """Bind the port on every address whose holder would contend for it, and release each one.

    SO_REUSEADDR is set because uvicorn sets it, so the probe fails exactly where uvicorn's own
    bind would - except for the case that option creates: a specific address binds happily under
    a wildcard listener, so the wildcards are probed too and a port already spoken for on this
    machine is refused rather than quietly shared. An address this machine cannot offer is
    skipped rather than raised: a host with no IPv6 stack has no IPv6 listener either, so its
    absence says nothing about whether the port is free.
    """
    for family, address in _probe_addresses(host, port):
        probe = socket.socket(family, socket.SOCK_STREAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((address, port))
        except OSError as error:
            if error.errno in _ADDRESS_UNAVAILABLE_ERRNOS:
                continue
            raise
        finally:
            probe.close()


def _address_already_in_use(host: str, port: int) -> bool:
    """Whether binding (host, port) fails with EADDRINUSE on either stack right now."""
    try:
        _bind_probe(host, port)
    except OSError as error:
        return error.errno == errno.EADDRINUSE
    return False


def _preflight_bind(host: str, port: int) -> None:
    """Refuse a taken port before anything says the server is starting.

    The probe claims the address on every stack the host names and releases it, so a port held
    by something else - typically 8080, where a local DHIS2 stack lives - fails as one line
    before the banner and before the app's lifespan loads a store. A holder on either stack
    refuses the run, because a browser asking this machine for that port may be routed to
    either one. The port can still be taken between this probe and uvicorn's own bind; that
    race is accepted, and `_run_server` renders the same one-line refusal when it loses, so
    the window narrows without reopening the traceback.
    """
    try:
        _bind_probe(host, port)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise PortInUseError(host=host, port=port) from error
        raise


@app.command("serve")
def serve_command(
    directory: Annotated[
        Path, typer.Argument(file_okay=False, help="Project directory (default: current directory).")
    ] = Path("."),
    live: Annotated[
        bool,
        typer.Option(
            "--live",
            help="Build the served resources from a DHIS2 instance at startup instead of reading the "
            "compiled IG off disk. The store is a snapshot of the instance the server started against, "
            "and the one client that built it stays open for the life of the process, because the "
            "register routes read the instance per request.",
        ),
    ] = False,
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            help="Interface to bind, overriding `\\[serve] host`. The default is loopback. Binding "
            "anything else while neither --auth nor `\\[serve] auth` states a posture is refused: who "
            "reaches this facade and who it answers are one decision.",
        ),
    ] = None,
    port: Annotated[
        int | None, typer.Option("--port", help="Port to listen on, overriding `\\[serve] port` (default 8080).")
    ] = None,
    auth: Annotated[
        ServeAuth | None,
        typer.Option(
            "--auth",
            help="Who this facade serves, overriding `\\[serve] auth`. `none` serves every caller; "
            "`token` takes a static bearer token out of D2W_FHIR_SERVE_TOKENS; `dhis2` takes the "
            "caller's own DHIS2 credentials and checks them against the instance this run reads, "
            "which needs --live; `jwt` takes a token from the OpenID Connect issuer named in "
            "`\\[serve.jwt] issuer`, verified against that issuer's published keys. Binding an "
            "interface other than loopback while neither this flag nor fhir.toml states a posture "
            "is refused.",
        ),
    ] = None,
    auth_scope: Annotated[
        ServeAuthScope | None,
        typer.Option(
            "--auth-scope",
            help="How much of the surface the posture covers, overriding `\\[serve] auth_scope`. "
            "`write` asks for credentials on `POST /QuestionnaireResponse` and leaves every read "
            "open; `all` asks for them everywhere except `/metadata`, which stays open so a client "
            "can read the posture it has to meet.",
        ),
    ] = None,
    registry_package: Annotated[
        Path | None,
        typer.Option(
            "--registry-package",
            help="The organisation-unit registry package to serve this guide's units from - the "
            "`package.tgz` the registry project's `make build` wrote, or a directory it was "
            r"extracted into. Only for a guide naming `\[generate.organisation_units.registry]`, and "
            "only when no `path` checkout answers: the checkout is read first.",
        ),
    ] = None,
    strict_codes: Annotated[
        bool | None,
        typer.Option(
            "--strict-codes/--no-strict-codes",
            help="Refuse a received answer whose code is outside the served terminology, overriding "
            "`\\[serve] strict_codes`. The default records the drift as a warning and stores the "
            "submission, because an option added to the instance since the IG was built is a fact about "
            "the instance, not a client mistake.",
        ),
    ] = None,
    ui: Annotated[
        bool | None,
        typer.Option(
            "--ui/--no-ui",
            help="Serve the capture UI at `/` alongside the FHIR routes, overriding `\\[serve] ui`. "
            "The bundle is mounted around them and shadows none of them, and the run names the build "
            "it is serving. In a checkout, a bundle older than the frontend source beside it is refused "
            "rather than served: `make ui` builds it, and the refusal says so.",
        ),
    ] = None,
    basemap: Annotated[
        list[str] | None,
        typer.Option(
            "--basemap",
            help="Raster tile layer the capture UI's organisation-unit map offers under the "
            "boundaries, overriding `\\[serve.basemaps]` (default: OpenStreetMap's standard tiles). "
            "Repeat it to offer several: `Name=https://.../{z}/{x}/{y}.png`, or a bare template "
            "named after its host. The map's layer control always carries a None entry beside them, "
            "and `--basemap none` offers nothing else - which is what an air-gapped deployment "
            "wants, the tiles being the only thing in the UI that reaches an origin other than "
            "this server.",
        ),
    ] = None,
) -> None:
    r"""Serve the project's IG as a FHIR read and capture facade over HTTP.

    Reads answer from what the IG publishes.

    Two APIs answer. FHIR is at the base URL and its contract is the CapabilityStatement at
    `/metadata`; this facade's own controls - the receipts, the settings, the caller, the evaluator,
    the vocabularies, the register listings - are at `/facade`, described by the OpenAPI document at
    `/facade/openapi.json` and browsable at `/facade/docs`.

    Received QuestionnaireResponses are stored as receipts, so reading one back says what was submitted.

    `--live` builds the store from the instance at startup, as the profile `d2w -p` names.

    `--ui` also serves the capture UI at `/`, same-origin with the FHIR routes it reads.

    `--basemap` offers another tile layer on the organisation-unit map, and `--basemap none` offers none.

    `--auth` says who is served: `none`, `token` (D2W_FHIR_SERVE_TOKENS), `dhis2` (the caller's own
    credentials), or `jwt` (a token from the OpenID Connect issuer named in `\[serve.jwt] issuer`,
    verified against that issuer's published keys).

    Host, port, authentication, strict codes, the UI, and basemaps come from `\[serve]` unless a flag beats them.

    Two more `\[serve]` keys have no flag, and are set in fhir.toml alone: `capture = false` serves
    the guide and receives nothing, and `spool_dir` says where the receipts live - the same directory
    `d2w fhir forward` drains, which is why one project states it once rather than per invocation.
    """
    try:
        from dhis2w_fhir_serve import ServeAuthConfigurationError, ServeSettings, configure_logging, create_app

        # The stamp exists so the capture UI can be told apart from the last one built, which keeps it
        # off the serve package's library surface: it is read from its own module, not the package root.
        from dhis2w_fhir_serve.ui import read_ui_build_stamp
    except ImportError as error:
        raise LookupError(_serve_package_missing("serve")) from error

    project = load_project(directory)
    # The precedence, the profile, and the preflight on the compiled guide belong to
    # `ServeSettings.resolve`, in `dhis2w-fhir-serve`, so an embedded facade asks for the posture
    # this command has by name and the two cannot disagree about what a flag beats or when an
    # unknown profile refuses a run. The one `ValueError` it raises is a `--basemap` value that
    # names nothing servable, which is this command's to render against the flag it came from.
    try:
        invocation = ServeSettings.resolve(
            project,
            live=live,
            host=host,
            port=port,
            strict_codes=strict_codes,
            ui=ui,
            basemaps=basemap,
            auth=auth,
            auth_scope=auth_scope,
            registry_package=registry_package,
        )
    except ServeAuthConfigurationError as error:
        raise typer.BadParameter(str(error), param_hint="--auth") from error
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--basemap") from error
    settings = invocation.settings
    generation = invocation.generation
    _preflight_bind(invocation.host, invocation.port)
    configure_logging()
    # The app is built before the banner so a missing or stale UI bundle refuses as one line here,
    # the way a taken port does, rather than under a message saying the server is starting.
    application = create_app(settings)
    surface = _serve_surface(capture=settings.capture, ui=settings.ui, publishes=settings.publishes)
    _line(
        f"starting {project.project_root} on http://{invocation.host}:{invocation.port} as a {surface} (ctrl-c to stop)"
    )
    if settings.ui:
        # The bundle is a build artifact, so the run says which one it is serving. A checkout with a
        # stale one never reaches this line; a wheel's bundle is whatever the release packaged.
        stamp = read_ui_build_stamp()
        _hint("bundle", stamp.describe() if stamp is not None else "the capture UI bundle carries no build stamp")
        _hint(
            "links",
            f"the screens link identities into {generation.profile.base_url} ({generation.name}, "
            f"from {generation.origin})"
            if generation is not None
            else "no profile resolved, so the screens link no identity to a DHIS2 instance",
        )
    _run_server(application, host=invocation.host, port=invocation.port)


def _serve_surface(*, capture: bool, ui: bool, publishes: str | None = None) -> str:
    """What one run is, as the starting line names it: what it serves, and whether it receives.

    A run that receives nothing says so on the line that starts it, because every other sign of it
    is a refusal somebody meets later - a 405 on a submission, a Submit the screens will not offer.

    A package says what it publishes rather than what it receives: it holds no form, so "receiving
    no submissions" would read as a dial somebody turned off rather than as the shape of the project.
    """
    from dhis2w_fhir_serve import package_subject

    surface = ("FHIR endpoint + capture UI" if capture else "FHIR endpoint + screens") if ui else "FHIR endpoint"
    if publishes is not None:
        return f"{surface} publishing {package_subject(publishes)} and no forms"
    return surface if capture else f"{surface}, receiving no submissions"


def _run_server(application: Any, *, host: str, port: int) -> None:
    """Run one built facade under uvicorn until the process is interrupted.

    The server's own logging is switched off - `configure_logging` already put one line per
    request on stderr, and uvicorn's access log would double every one of them.

    A taken port normally fails in `_preflight_bind`, before the banner. When the port is
    taken inside the race window instead, uvicorn refuses it at its own bind - by raising
    the `OSError`, or by logging one line and calling `sys.exit(1)` - and both shapes are
    mapped to the same `PortInUseError` one-liner here, so neither can reach the terminal
    as a traceback. The `SystemExit` mapping re-probes the address first, because exit 1
    is also how uvicorn reports failures that are not about the port.
    """
    import uvicorn

    try:
        uvicorn.run(application, host=host, port=port, log_config=None, access_log=False)
    except KeyboardInterrupt as interrupt:
        raise typer.Exit(0) from interrupt
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise PortInUseError(host=host, port=port) from error
        raise
    except SystemExit as system_exit:
        if system_exit.code not in (0, None) and _address_already_in_use(host, port):
            raise PortInUseError(host=host, port=port) from system_exit
        raise


#: The basename the per-response outcomes of one forward run are written under, inside the reports directory.
_FORWARD_REPORT_STEM = "fhir-forward-report"

#: The banner a dry run closes with, once. It says the mode, what it did instead, and how to commit -
#: a run that reads as an import and was not one is the single worst thing this command could do. It
#: sits under the counts rather than over them, so it is the last thing on screen after the summary,
#: the rejection table and the hints; the mode row of the summary itself states the mode up front.
_DRY_RUN_BANNER = (
    "DRY RUN - every payload was posted to DHIS2 under its own validate-only mode "
    "(dataValueSets dryRun=true, tracker importMode=VALIDATE). Nothing was written to the instance and "
    "no receipt moved. Re-run with --import to commit."
)

#: The Rich style each outcome kind renders in, so a glance separates what landed from what did not.
_OUTCOME_STYLES = {
    "accepted": "green",
    "rejected": "red",
    "refused": "yellow",
    "unverifiable": "cyan",
    "not-posted": "yellow",
}


def _outcome_cell(value: Any) -> str:
    """Render one outcome kind in the style it carries."""
    kind = str(value)
    return f"[{_OUTCOME_STYLES.get(kind, 'default')}]{kind}[/]"


#: How many of a rejection's reasons the terminal cell shows before it counts the rest. DHIS2 names one
#: row per broken rule, and a response breaking six of them would otherwise own the whole table width.
_TERMINAL_REASON_SAMPLE = 1

#: How many of a rejection's reasons the written report lists per response before it counts the rest.
_REPORT_REASON_SAMPLE = 5

#: The width one reason is truncated to in the terminal cell. The outcomes table has six columns, so
#: what a cell may claim is what the other five leave: a reason wide enough to squeeze a neighbour to
#: nothing costs more than it carries, and the written report is where a whole reason is read.
_REASON_CELL_WIDTH = 60

#: The width one spool path is truncated to in the terminal cell, for the same reason. A path is
#: truncated from its front rather than its end, because the receipt's own file name is the half that
#: says which response the row is - and the directory above it repeats what the Outcome column states.
_SPOOL_CELL_WIDTH = 30


def _truncate(text: str, width: int) -> str:
    """One reason cut to the width a table cell has for it, with the cut marked rather than hidden.

    The ellipsis is spent out of the width rather than added to it, so what comes back is never
    wider than the cell it was cut for - which is what lets a caller add its own cells up.
    """
    return text if len(text) <= width else f"{text[: max(0, width - 3)]}..."


def _truncate_path(path: str, width: int) -> str:
    """One path cut to the width a table cell has for it, keeping the end - which is what names the file."""
    return path if len(path) <= width else f"...{path[-(width - 3) :]}"


def _outcome_reasons(outcome: ForwardOutcome, sample: int, width: int | None = None) -> str:
    """Why this response ended where it did: DHIS2's rows for a rejection, the translator's for a refusal.

    A rejection that DHIS2 named no row for still says something - the message off the envelope - because
    "rejected" with nothing beside it is the one thing a reader cannot act on. A response refused as an
    overwrite reads its covered values, which are the whole of why it stayed in the queue.
    """
    if outcome.overwrite_refused:
        lines = [value.line for value in outcome.overwritten_values]
    elif outcome.refusals:
        lines = [f"{refusal.category}: {refusal.reason}" for refusal in outcome.refusals]
    else:
        imported = outcome.import_outcome
        if imported is None:
            return ""
        lines = [issue.line for issue in imported.issues]
        if not lines:
            lines = [imported.message] if imported.message else []
        if not lines:
            return imported.counts_line
    shown = [_truncate(line, width) if width else line for line in lines[:sample]]
    remaining = len(lines) - len(shown)
    return "; ".join(shown) + (f" (+{remaining} more)" if remaining else "")


def _render_rejection_reasons(report: ForwardReport) -> None:
    """Roll every rejection up by cause, so two hundred of them read as the handful of rules they broke."""
    reasons = report.rejection_reasons
    if not reasons:
        return
    render_list(
        "rejection reasons",
        [
            {
                "code": reason.error_code or "",
                "reason": reason.reason,
                "responses": str(reason.responses),
            }
            for reason in reasons
        ],
        [
            ColumnSpec("Code", "code", no_wrap=True),
            ColumnSpec("What DHIS2 said", "reason"),
            ColumnSpec("Responses", "responses", no_wrap=True),
        ],
        console=STDERR_CONSOLE,
    )


def _render_unverifiable_reasons(report: ForwardReport) -> None:
    """State what this dry run could not check and why, so nobody reads it as data DHIS2 turned down."""
    reasons = report.unverifiable_reasons
    if not reasons:
        return
    render_list(
        "unverifiable",
        [{"reason": reason.reason, "responses": str(reason.responses)} for reason in reasons],
        [
            ColumnSpec("What a dry run cannot check", "reason"),
            ColumnSpec("Responses", "responses", no_wrap=True),
        ],
        console=STDERR_CONSOLE,
    )


#: The Rich style each completeness outcome renders in, matching the outcome palette a row above it.
_COMPLETENESS_STYLES = {
    "registered": "green",
    "would-register": "cyan",
    "not-claimed": "dim",
    "not-registered": "dim",
    "refused": "red",
    "pending": "yellow",
}


def _completeness_cell(value: Any) -> str:
    """Render one completeness outcome kind in the style it carries."""
    kind = str(value)
    return f"[{_COMPLETENESS_STYLES.get(kind, 'default')}]{kind}[/]"


def _render_completeness(report: ForwardReport) -> None:
    """State what every aggregate response of the run claimed about completeness, and what came of it."""
    from dhis2w_fhir.service import ForwardCompletenessKind

    outcomes = report.completeness_outcomes
    if not outcomes:
        return
    render_list(
        "data set completeness",
        [
            {
                "outcome": outcome.kind,
                "tuple": outcome.tuple_line,
                "date": outcome.date or "",
                "reason": outcome.reason if outcome.kind == ForwardCompletenessKind.REFUSED else "",
            }
            for outcome in outcomes
        ],
        [
            ColumnSpec("Completeness", "outcome", formatter=_completeness_cell, no_wrap=True),
            ColumnSpec("Data set / period / organisation unit / attribute option combo", "tuple"),
            ColumnSpec("Completed on", "date", no_wrap=True),
            ColumnSpec("Why", "reason"),
        ],
        console=STDERR_CONSOLE,
    )


def _render_overwritten_values(report: ForwardReport) -> None:
    """Name every value the run met that an earlier submission had already sent, and which one sent it."""
    overwrites = report.overwrites
    if not overwrites:
        return
    render_list(
        "values a previous submission already sent",
        [
            {
                "response": overwrite.response_id,
                "value": value.cell.line,
                "previous": value.previous_response_id,
                "received": value.previous_received_at,
            }
            for overwrite in overwrites
            for value in overwrite.values
        ],
        [
            ColumnSpec("Response", "response"),
            ColumnSpec(
                "Data element / category option combo / period / organisation unit / attribute option combo", "value"
            ),
            ColumnSpec("Sent before by", "previous"),
            ColumnSpec("Received", "received", no_wrap=True),
        ],
        console=STDERR_CONSOLE,
    )


def _render_forward_outcomes(report: ForwardReport) -> None:
    """List every response the run drained, with what became of it and why."""
    if not report.outcomes:
        return
    render_list(
        "responses",
        [
            {
                "response": outcome.response_id,
                "target": outcome.target_kind or "",
                "outcome": outcome.kind,
                "notes": str(len(outcome.notes)),
                "reason": _outcome_reasons(outcome, _TERMINAL_REASON_SAMPLE, _REASON_CELL_WIDTH),
                "spool": _truncate_path(outcome.spool_path, _SPOOL_CELL_WIDTH),
            }
            for outcome in report.outcomes
        ],
        [
            # A receipt id is thirty-two characters and every row carries one, so holding it on a
            # single line claims most of an eighty-column fall-back and leaves the two columns that
            # explain the row a character apiece. It folds; the four short columns do not.
            ColumnSpec("Response", "response"),
            ColumnSpec("Target", "target", no_wrap=True),
            ColumnSpec("Outcome", "outcome", formatter=_outcome_cell, no_wrap=True),
            ColumnSpec("Notes", "notes", no_wrap=True),
            ColumnSpec("Why", "reason"),
            ColumnSpec("Spool", "spool"),
        ],
        console=STDERR_CONSOLE,
    )


def _completeness_report_lines(report: ForwardReport) -> list[str]:
    """The written report's completeness section: the tuple every aggregate response claimed, and its answer."""
    from dhis2w_fhir.service import ForwardCompletenessKind

    outcomes = report.completeness_outcomes
    if not outcomes:
        return []
    lines = [
        "## Data set completeness",
        "",
        "An aggregate response whose status is `completed` registers the data set complete for the",
        "tuple its values landed under. The registration is a second write, made only once DHIS2 has",
        "taken the values; a response reporting itself `in-progress` imports its values and claims",
        "nothing. A refused registration does not un-import the values - they are imported and stay",
        "imported, and forwarding the same tuple again registers it.",
        "",
        "| Completeness | Data set | Period | Organisation unit | Attribute option combo | Completed on | Why |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {outcome.kind} | {outcome.data_set or ''} | {outcome.period or ''} | "
        f"{outcome.organisation_unit or ''} | {outcome.attribute_option_combo or ''} | {outcome.date or ''} | "
        f"{outcome.reason if outcome.kind == ForwardCompletenessKind.REFUSED else ''} |"
        for outcome in outcomes
    )
    lines.append("")
    reason = report.completeness_dry_run_reason
    if reason:
        lines.extend([reason, ""])
    return lines


#: What the written report says about the values an import replaced, above the table naming them. The
#: fact a reader needs first is that DHIS2 counted the write the same way it counts a first entry, so
#: this section is the only place the run can state which is which.
_OVERWRITE_IMPORT_PREAMBLE = (
    "Each value below was sent to DHIS2 by a receipt this spool has already forwarded, and this run",
    "sent it again. The instance now holds the number this run's response carried.",
    "",
    "DHIS2 keeps the newest number for a value and counts writing it exactly as it counts a first",
    "entry, so no import summary separates a correction from a first entry, and this run states it",
    "here instead.",
)

#: The same section on a dry run, where nothing has been written and the whole point is that there is
#: still time to act on it.
_OVERWRITE_DRY_RUN_PREAMBLE = (
    "Each value below was sent to DHIS2 by a receipt this spool has already forwarded, and this run",
    "would send it again. Nothing has changed in the instance: this run wrote nothing.",
    "",
    "An import replaces each number below with the one this run's response carries. DHIS2 counts that",
    "write exactly as it counts a first entry, so no import summary would separate the two afterwards.",
)

#: The same section under `[forward] overwrites = "refuse"`, where the values below are what the run
#: refused over rather than what it replaced. The response is what is refused, never the value: a
#: payload posted in part would tear one submission across two postures.
_OVERWRITE_REFUSED_PREAMBLE = (
    "Each value below was sent to DHIS2 by a receipt this spool has already forwarded, and this run",
    'carries it again. `[forward] overwrites = "refuse"` is set, so none of it was sent: a response',
    "holding any of these values is refused whole and stays in `.serve/responses/received/`.",
    "",
    "Nothing in the instance changed, and nothing about these responses is decided. `overwrites =",
    '"allow"` - or `--overwrites allow` for one run - posts them and names each replaced value',
    "instead.",
)


def _overwrite_preamble(report: ForwardReport) -> tuple[str, ...]:
    """Which of the three things the written report's overwrite section is about, for this run's posture."""
    if report.overwrite_posture is OverwritePosture.REFUSE:
        return _OVERWRITE_REFUSED_PREAMBLE
    return _OVERWRITE_DRY_RUN_PREAMBLE if report.dry_run else _OVERWRITE_IMPORT_PREAMBLE


def _overwritten_value_report_lines(report: ForwardReport) -> list[str]:
    """The written report's section for the values this run sent that an earlier submission had sent."""
    overwrites = report.overwrites
    if not overwrites and not report.forwarded_without_values:
        return []
    lines = ["## Values a previous submission already sent", ""]
    if overwrites:
        lines.extend(
            [
                *_overwrite_preamble(report),
                "",
                "The earlier receipt is named so the submission it came from can be read: it is",
                "`.serve/responses/forwarded/<id>.json`, with what DHIS2 did with it in `<id>.report.json`",
                "beside it.",
                "",
                "| Response | Data element | Category option combo | Period | Organisation unit "
                "| Attribute option combo | Sent before by | Received |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| {overwrite.response_id} | {value.cell.data_element} | {value.cell.category_option_combo or ''} | "
            f"{value.cell.period or ''} | {value.cell.organisation_unit or ''} | "
            f"{value.cell.attribute_option_combo or ''} | {value.previous_response_id} | "
            f"{value.previous_received_at} |"
            for overwrite in overwrites
            for value in overwrite.values
        )
        lines.append("")
    if report.forwarded_without_values:
        lines.extend(
            [
                f"{report.forwarded_without_values} receipt(s) DHIS2 has already accepted record no values, so "
                "this run cannot say whether any of them sent these values first. Every receipt a drain files "
                "records what it sent, so a receipt that records nothing is one something else put in "
                "`.serve/responses/forwarded/`.",
                "",
            ]
        )
    return lines


def _write_forward_report(report: ForwardReport, generation: GenerationProfile) -> Path:
    """Write every response's outcome to `reports/fhir-forward-report.md`, grouped by what became of it."""
    from datetime import UTC, datetime

    from dhis2w_fhir import REPORTS_DIRECTORY

    directory = report.project_root / REPORTS_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        "# fhir forward report",
        "",
        f"- Profile: {generation.name} ({generation.profile.base_url})",
        f"- Mode: {'dry run (validate only)' if report.dry_run else 'import'}",
        f"- Coded answers: {report.coded_answer_mode}",
        f"- Data set completeness: {report.completeness_line or 'no aggregate response claimed any'}",
        f"- Values a previous submission already sent: {report.overwrite_line or 'none'}",
        f"- Overwrites: {report.overwrite_posture}",
        f"- Forwarded: {datetime.now(tz=UTC).isoformat(timespec='seconds')}",
        f"- Counts: {report.counts_line}",
        "",
    ]
    if report.stopped is not None:
        lines.extend(
            [
                "## The drain stopped early",
                "",
                f"It stopped at `{report.stopped.response_id}`: {report.stopped.reason}",
                "",
                f"{len(report.not_posted)} response(s) were never posted. They are untouched in the queue, "
                "as is the receipt that met the failure, so forwarding again once the instance is healthy "
                "is the retry.",
                "",
            ]
        )
    if report.quarantined:
        lines.extend(
            [
                "## Files that do not read as receipts",
                "",
                "Each was moved to `.serve/responses/malformed/` with its reason written beside it, and this",
                "run carried on with everything else. Nothing in that directory is a receipt.",
                "",
                "| File | What stopped it |",
                "| --- | --- |",
            ]
        )
        lines.extend(f"| `{entry.file_name}` | {entry.reason} |" for entry in report.quarantined)
        lines.append("")
    if report.filing_issues:
        lines.extend(
            [
                "## Receipts whose file had already moved",
                "",
                "DHIS2 answered about each of these, and the answer is in this report - but the file was gone",
                "when the run went to file it, so it is wherever whatever moved it put it.",
                "",
            ]
        )
        lines.extend(f"- `{issue.response_id}` - {issue.reason}" for issue in report.filing_issues)
        lines.append("")
    reasons = report.rejection_reasons
    if reasons:
        lines.extend(
            [
                "## Rejection reasons",
                "",
                "Every rejection of this run rolled up by cause, commonest first. A response counts once",
                "per distinct cause it met, and the identifiers DHIS2 quotes in a message are generalised",
                "away, so one broken rule reads as one row however many responses met it.",
                "",
                "| Responses | Code | What DHIS2 said |",
                "| --- | --- | --- |",
            ]
        )
        lines.extend(f"| {reason.responses} | {reason.error_code or ''} | {reason.reason} |" for reason in reasons)
        lines.append("")
    unverifiable_reasons = report.unverifiable_reasons
    if unverifiable_reasons:
        lines.extend(["## What a dry run could not check", ""])
        for reason in unverifiable_reasons:
            lines.extend([f"{reason.reason} ({reason.responses} response(s))", ""])
    lines.extend(_overwritten_value_report_lines(report))
    lines.extend(_completeness_report_lines(report))
    for heading, outcomes in (
        ("Rejected by DHIS2", report.rejected),
        ("Unverifiable in a dry run", report.unverifiable),
        ("Refused by the translator", report.translator_refused),
        ("Refused as an overwrite", report.overwrite_refused),
        ("Not yet sent to DHIS2", report.not_posted),
        ("Accepted", report.accepted),
    ):
        if not outcomes:
            continue
        lines.extend([f"## {heading}", ""])
        for outcome in outcomes:
            target = outcome.target_kind or "no payload"
            lines.append(
                f"- `{outcome.response_id}` ({outcome.questionnaire or 'no form'}) - {target} - {outcome.spool_path}"
            )
            if outcome.submitted_by:
                lines.append(f"    - captured by {outcome.submitted_by}")
            imported = outcome.import_outcome
            if imported is not None and imported.issues:
                lines.extend(f"    - {issue.line}" for issue in imported.issues[:_REPORT_REASON_SAMPLE])
                remaining = len(imported.issues) - _REPORT_REASON_SAMPLE
                if remaining > 0:
                    lines.append(f"    - (+{remaining} more reason(s))")
            else:
                detail = _outcome_reasons(outcome, _REPORT_REASON_SAMPLE)
                if detail:
                    lines.append(f"    - {detail}")
            lines.extend(f"    - note: {note.category}: {note.message}" for note in outcome.notes)
        lines.append("")
    destination = directory / f"{_FORWARD_REPORT_STEM}.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def _render_overwrite_hints(report: ForwardReport) -> None:
    """State that this run met values an earlier submission had sent, which DHIS2's own answer cannot."""
    overwrites = report.overwrites
    if overwrites and report.overwrite_posture is OverwritePosture.REFUSE:
        refused = len(report.overwrite_refused)
        values = report.overwritten_value_count
        _hint(
            "note",
            f"{refused} response(s) were not sent: each carries {values} value(s) in all that a receipt this "
            "spool has already forwarded sent, and `[forward] overwrites` is `refuse`. They are still in the "
            "queue"
            + (
                ", each with the covered values written down beside it, and `--overwrites allow` posts them"
                if not report.dry_run
                else " - this run wrote nothing at all, and `--overwrites allow` posts them"
            ),
            style="yellow",
        )
    elif overwrites:
        values = report.overwritten_value_count
        _hint(
            "note",
            (
                f"{len(overwrites)} response(s) sent {values} value(s) an earlier submission had already sent, "
                "and the instance now holds the numbers these responses carried. DHIS2 counts that write "
                "exactly as it counts a first entry, so nothing in the import summary says it happened - the "
                "report names each value and the receipt that sent it before"
                if not report.dry_run
                else f"{len(overwrites)} response(s) carry {values} value(s) an earlier submission has already "
                "sent. Nothing has changed in the instance yet, and an import replaces those numbers with the "
                "ones these responses carry - the report names each value and the receipt that sent it before"
            ),
            style="yellow",
        )
    if report.forwarded_without_values:
        _hint(
            "note",
            f"{report.forwarded_without_values} receipt(s) DHIS2 has already accepted record no values, so this "
            "run cannot say whether they sent any of these values first",
        )


def _render_completeness_hints(report: ForwardReport) -> None:
    """Say what a completeness refusal means for the values, which is the one thing a reader must not guess."""
    from dhis2w_fhir.service import ForwardCompletenessKind

    refused = report.completeness_of(ForwardCompletenessKind.REFUSED)
    if refused:
        _hint(
            "note",
            f"{len(refused)} report(s) imported and DHIS2 refused the completeness registration. The values "
            "are imported and stay imported - only the completeness claim failed. Forwarding the same tuple "
            "again registers it; a tuple registered twice is an update, not a conflict.",
            style="yellow",
        )
    pending = report.completeness_of(ForwardCompletenessKind.PENDING)
    if pending:
        _hint(
            "note",
            f"{len(pending)} report(s) imported and the completeness registration is not known to have "
            "landed. The values are imported and stay imported, and the claim is written into the "
            "forwarded receipt's own report - the next importing run posts it again on its own.",
            style="yellow",
        )
    retries = report.completeness_retries
    if retries:
        _hint("note", f"This run also posted {report.completeness_retry_line}.")
    reason = report.completeness_dry_run_reason
    if reason:
        _hint("note", reason)


def _render_forward_report(report: ForwardReport, generation: GenerationProfile, *, details: bool) -> None:
    """Render one forward run: the mode first, the counts, then either every response or where they are."""
    render_detail(
        "fhir forward",
        [
            DetailRow("profile", f"{generation.name} ({generation.origin})"),
            DetailRow("project", str(report.project_root)),
            DetailRow("mode", "DRY RUN (validate only)" if report.dry_run else "import"),
            DetailRow("coded answers", str(report.coded_answer_mode)),
            DetailRow("spooled", str(report.spooled)),
            DetailRow("translated", str(report.translated_count)),
            DetailRow("refused", str(len(report.refused))),
            DetailRow("posted", str(report.posted_count)),
            DetailRow("accepted", str(len(report.accepted))),
            DetailRow("rejected", str(len(report.rejected))),
            *([DetailRow("unverifiable", str(len(report.unverifiable)))] if report.dry_run else []),
            *([DetailRow("data set completeness", report.completeness_line)] if report.completeness_line else []),
            *(
                [DetailRow("values a previous submission already sent", report.overwrite_line)]
                if report.overwrite_line
                else []
            ),
            *(
                [DetailRow("overwrites", str(report.overwrite_posture))]
                if report.overwrite_posture is OverwritePosture.REFUSE or report.overwrite_line
                else []
            ),
            *(
                [DetailRow("corrections", str(report.correction_posture))]
                if report.correction_posture is not CorrectionPosture.OFF
                else []
            ),
            *(
                [DetailRow("withdrawals", str(report.withdrawal_posture))]
                if report.withdrawal_posture is not WithdrawalPosture.OFF
                else []
            ),
            *([DetailRow("not posted", str(len(report.not_posted)))] if report.stopped is not None else []),
        ],
        console=STDERR_CONSOLE,
    )
    for unreadable in report.unreadable_artifacts:
        _hint("note", f"published resource left out of the translation context: {unreadable}")
    for quarantined in report.quarantined:
        _hint(
            "note",
            f"{quarantined.file_name} does not read as a receipt and was moved to "
            f"{MALFORMED_RESPONSES_RELATIVE_PATH}: {quarantined.reason}",
        )
    for issue in report.filing_issues:
        _hint("note", f"{issue.response_id}: {issue.reason}")
    destination = _write_forward_report(report, generation)
    if not report.spooled:
        _hint("note", "the spool is empty - `d2w fhir serve` is what fills it")
        return
    _render_rejection_reasons(report)
    _render_unverifiable_reasons(report)
    if details:
        _render_overwritten_values(report)
        _render_completeness(report)
        _render_forward_outcomes(report)
        _hint("note", f"this run's outcomes are also written to {destination}")
    else:
        noted = sum(len(outcome.notes) for outcome in report.outcomes)
        _hint(
            "note",
            f"{len(report.outcomes)} response(s), {noted} note(s); full outcomes in {destination} (--details to print)",
        )
    if report.stopped is not None:
        _hint(
            "error",
            f"the drain stopped at `{report.stopped.response_id}` - {report.stopped.reason}. "
            f"{len(report.not_posted)} response(s) were never posted and are untouched in the queue; "
            "forwarding again once the instance is healthy is the retry",
            style="red",
        )
    if report.rejected:
        _hint(
            "error",
            f"{len(report.rejected)} response(s) rejected by DHIS2; exiting 1 - read the import summary, fix "
            "the instance or the data, and forward again",
            style="red",
        )
    if report.translator_refused:
        _hint(
            "error",
            f"{len(report.translator_refused)} response(s) refused by the translator; exiting 1 - they stay in "
            "the spool, so fixing the guide or the data and forwarding again is the retry",
            style="red",
        )
    if report.unverifiable:
        _hint(
            "note",
            f"{len(report.unverifiable)} response(s) this dry run could not check - each is a stage event whose "
            "enrollment a registration of the same run creates, and only an import creates it",
        )
    _render_overwrite_hints(report)
    _render_completeness_hints(report)
    if report.dry_run:
        _hint("dry run", _DRY_RUN_BANNER, style="bold yellow")


@app.command("forward")
def forward_command(
    directory: Annotated[
        Path, typer.Argument(file_okay=False, help="Project directory (default: current directory).")
    ] = Path("."),
    import_responses: Annotated[
        bool | None,
        typer.Option(
            "--import/--dry-run",
            help="Commit the payloads to DHIS2 and move the receipts, overriding `\\[forward] import`. "
            "The default is a dry run: every payload still goes to the real endpoint under its own "
            "validate-only mode, and nothing is written and nothing moves.",
        ),
    ] = None,
    strict_codes: Annotated[
        bool | None,
        typer.Option(
            "--strict-codes/--no-strict-codes",
            help="Refuse a coded answer whose code is outside the served terminology, overriding "
            "`\\[serve] strict_codes`. Lenient resolves the DHIS2 option UID and code too, and notes it.",
        ),
    ] = None,
    register_completeness: Annotated[
        bool | None,
        typer.Option(
            "--register-completeness/--no-register-completeness",
            help="Register the data set complete for every aggregate response whose status is `completed`, "
            "once DHIS2 has taken its values, overriding `\\[forward] register_completeness`. On by "
            "default - the response said it was finished.",
        ),
    ] = None,
    overwrites: Annotated[
        OverwritePosture | None,
        typer.Option(
            "--overwrites",
            help="What to do with an aggregate value a forwarded receipt already sent, overriding "
            "`\\[forward] overwrites`. `allow` - the default - posts it and names it; `refuse` leaves "
            "the whole response in the queue with the covered values written down beside it.",
        ),
    ] = None,
    corrections: Annotated[
        CorrectionPosture | None,
        typer.Option(
            "--corrections",
            help="Whether this deployment accepts a submission that names the receipt it corrects, "
            "overriding `\\[forward] corrections`. Off by default. Stated by the run rather than acted "
            "on by it - a drain imports, and a correction lands on the corrected receipt's identity.",
        ),
    ] = None,
    withdrawals: Annotated[
        WithdrawalPosture | None,
        typer.Option(
            "--withdrawals",
            help="Whether this deployment retracts what it forwarded, overriding "
            "`\\[forward] withdrawals`. Off by default, and read by `d2w fhir withdraw` rather than by "
            "the drain, which never deletes anything.",
        ),
    ] = None,
    registry_package: Annotated[
        Path | None,
        typer.Option(
            "--registry-package",
            help="The organisation-unit registry package to resolve this guide's unit references "
            "through - the `package.tgz` the registry project's `make build` wrote, or a directory "
            r"it was extracted into. Only for a guide naming `\[generate.organisation_units.registry]`, "
            "and only when no `path` checkout answers: the checkout is read first.",
        ),
    ] = None,
    details: Annotated[
        bool,
        typer.Option(
            "--details",
            help="Print every response's outcome here as well. The report is written either way.",
        ),
    ] = False,
    progress: ProgressOption = True,
) -> None:
    r"""Drain the capture spool into DHIS2 - translate every received response and post it.

    DRY RUN IS THE DEFAULT. Every payload is posted to the real instance under the endpoint's own
    validate-only mode, so DHIS2's rules decide the answer and nothing is written; `--import` commits.

    The posture comes from `\[forward]` in fhir.toml - `import`, `register_completeness`,
    `overwrites`, `corrections`, and `withdrawals` - unless a flag here overrides it for this run,
    and from the defaults above when the file states none.

    Which spool is drained has no flag: it is `\[serve] spool_dir` in fhir.toml, the same key the
    server writes receipts under, so a project that moves its receipt tree moves it for both halves
    of the loop at once.

    `corrections` and `withdrawals` are the deployment's posture towards a submission that names what
    it amends or retracts, and the run states them rather than acting on them: a drain imports, and
    `d2w fhir withdraw` is what reads `withdrawals`.

    An imported response moves from the spool's received/ to forwarded/, a DHIS2-rejected one to
    rejected/ beside a report, and a translator-refused one stays put - fix and forward again.

    A guide whose organisation units a registry package publishes resolves every unit reference
    through that package - the `path` checkout, or `--registry-package` - however the guide itself
    was read, and a package neither source supplies refuses the drain rather than translating
    against places this guide does not publish.

    Every payload names its own DHIS2 object - an event's UID is derived from the receipt's logical id -
    so one receipt forwarded twice is refused as an object the instance holds, never imported twice.

    An aggregate response whose status is `completed` also registers the data set complete for the
    period, organisation unit, and attribute option combo its values landed under - a second write,
    made only after DHIS2 has taken the values. `in-progress` imports the values and registers
    nothing, and `--no-register-completeness` turns the second write off for the whole run.

    A value an earlier submission already sent is named in the run, with the receipt that sent it and
    when that receipt arrived. DHIS2 replaces such a value in place and counts the write exactly as it
    counts a first entry, so no import summary can say it happened; a dry run says it too, while there
    is still time to act on it. `--overwrites refuse` leaves any response holding one in the queue,
    with each covered value written down beside it, instead of posting it.

    THE EXIT CODE. 0 exactly when nothing was refused by the translator, nothing was rejected by
    DHIS2, and the drain reached the end of the queue. Every other outcome exits 1 with the counts on
    screen: a partial drain is not a success, and neither is a drain that posted nothing because the
    translator refused everything it read. A dry run counts a stage event whose enrollment a
    registration of the same run creates as unverifiable rather than rejected - a dry run writes
    nothing, so there is no enrollment to check it against - and a run whose only failures are those
    exits 0.

    Outcomes land in reports/fhir-forward-report.md on every run, `--details` or not; `--details`
    prints them here as well.
    """
    from dhis2w_fhir import FORWARD_STEPS, service
    from dhis2w_fhir.conversion import CodedAnswerMode

    project = load_project(directory)
    generation = service.resolve_generation_profile(project)
    mode = None if strict_codes is None else (CodedAnswerMode.STRICT if strict_codes else CodedAnswerMode.LENIENT)
    with _progress(FORWARD_STEPS, enabled=progress) as reporter:
        report = asyncio.run(
            service.forward_responses(
                generation.profile,
                project,
                import_responses=import_responses,
                coded_answer_mode=mode,
                register_completeness=register_completeness,
                overwrites=overwrites,
                corrections=corrections,
                withdrawals=withdrawals,
                registry_package=registry_package,
                reporter=reporter,
            )
        )
        if reporter is not None:
            reporter.finish(report.counts_line)
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
    else:
        _render_forward_report(report, generation, details=details)
    if report.rejected or report.translator_refused or report.stopped is not None:
        raise typer.Exit(code=1)


#: The spool's receipts table, in the order its columns are rendered. The form's UID and the sentence
#: saying why a receipt is where it is carry a floor and an ellipsis: an 11-character UID rendered one
#: character to a line says nothing, so a terminal too narrow shortens the cell instead of folding it.
_RECEIPT_COLUMNS: list[ColumnSpec] = [
    ColumnSpec("Receipt", "id", no_wrap=True),
    ColumnSpec("State", "state", no_wrap=True),
    ColumnSpec("Form", "form", overflow="ellipsis", min_width=11),
    ColumnSpec("Received", "received", no_wrap=True),
    ColumnSpec("Captured by", "captured_by", no_wrap=True),
    ColumnSpec("Why it is there", "reason", overflow="ellipsis", min_width=16),
]

#: The receipt columns a narrow terminal loses, in the order they go. Both are on the receipt's own
#: file and in `--json`, and what is left is what a reader acts on: the id `requeue` and `withdraw`
#: take, the state, the form, and why the receipt is where it is. 80 columns is what a pipe gets.
_DROPPED_RECEIPT_COLUMNS_WHEN_NARROW = ("captured_by", "received")


def _fitted_receipt_columns(rows: list[dict[str, str]], width: int, *, attributed: bool) -> list[ColumnSpec]:
    """The widest receipt column set that fits the terminal, dropping the recoverable ones until it does."""
    columns = [column for column in _RECEIPT_COLUMNS if attributed or column.key != "captured_by"]
    for key in _DROPPED_RECEIPT_COLUMNS_WHEN_NARROW:
        if _table_width(columns, rows) <= width:
            break
        columns = [column for column in columns if column.key != key]
    return columns


def _render_spool_state(report: SpoolStateReport, *, details: bool) -> None:
    """Render one spool listing: the count in each state, then a row per receipt under `--details`."""
    render_detail(
        "fhir spool",
        [
            DetailRow("project", str(report.project_root)),
            DetailRow("not yet sent to DHIS2", str(report.counts.received)),
            DetailRow("refused by a drain, still queued", str(report.counts.refused_in_queue)),
            DetailRow("accepted by DHIS2", str(report.counts.forwarded)),
            DetailRow("refused by DHIS2", str(report.counts.rejected)),
            DetailRow("withdrawn from DHIS2", str(report.counts.withdrawn)),
            DetailRow("unreadable files", str(report.counts.malformed)),
        ],
        console=STDERR_CONSOLE,
    )
    if details and report.receipts:
        # The capture identity is a column only where there is one to show. Every receipt a
        # no-authentication facade wrote carries none, and a column of empty cells in a table that
        # already folds would cost the two columns that explain a row their width.
        attributed = any(row.submitted_by for row in report.receipts)
        rows = [
            {
                "id": row.response_id,
                "state": row.state.value,
                "form": row.questionnaire.rsplit("/", 1)[-1] or row.questionnaire,
                "received": row.received_at,
                "captured_by": row.submitted_by or "",
                "reason": row.reason or "",
            }
            for row in report.receipts
        ]
        render_list(
            "receipts",
            rows,
            _fitted_receipt_columns(rows, STDERR_CONSOLE.width, attributed=attributed),
            console=STDERR_CONSOLE,
        )
    if details and report.quarantined:
        render_list(
            "unreadable files",
            [{"file": entry.file_name, "reason": entry.reason} for entry in report.quarantined],
            [ColumnSpec("File", "file", no_wrap=True), ColumnSpec("What stopped it", "reason")],
            console=STDERR_CONSOLE,
        )
    if not report.receipts:
        _hint("note", "the spool holds no receipts - `d2w fhir serve` is what fills it")
        return
    if report.counts.malformed:
        _hint(
            "note",
            f"{report.counts.malformed} file(s) in {MALFORMED_RESPONSES_RELATIVE_PATH} do not read as receipts; "
            "each has its reason written beside it",
        )
    if report.counts.rejected:
        _hint(
            "note",
            f"{report.counts.rejected} receipt(s) were refused by DHIS2; fix the instance or the data and "
            "`d2w fhir requeue` puts them back in the queue",
        )
    if report.counts.refused_in_queue:
        _hint(
            "note",
            f"{report.counts.refused_in_queue} queued receipt(s) were refused on the last run that posted; the "
            "reason sits beside each receipt and the next `d2w fhir forward` retries them",
        )
    if not details:
        _hint("note", "--details lists every receipt")


@app.command("spool")
def spool_command(
    directory: Annotated[
        Path, typer.Argument(file_okay=False, help="Project directory (default: current directory).")
    ] = Path("."),
    details: Annotated[
        bool, typer.Option("--details", help="List every receipt, not just how many are in each state.")
    ] = False,
) -> None:
    """List the capture spool - how many receipts wait for DHIS2, and what became of the rest.

    Reads the project's own .serve/responses/ directory and nothing else: no DHIS2 connection, no
    profile, no network. Which directory a receipt's file is in is its state, and the report DHIS2's
    answer was written into says why a drained one is where it is.

    A file that does not read as a receipt is moved to .serve/responses/malformed/ with its reason
    beside it and counted there, so one unreadable file costs one row rather than the listing.
    """
    from dhis2w_fhir import service

    project = load_project(directory)
    report = service.read_spool_state(project)
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    _render_spool_state(report, details=details)


def _render_sync_report(report: SyncReport, generation: GenerationProfile) -> None:
    """Render one sync: what it read, what it changed per resource type, and where the cursor now stands."""
    render_detail(
        "fhir sync",
        [
            DetailRow("project", str(report.project_root)),
            DetailRow("instance", f"{generation.profile.base_url} ({generation.name}, from {generation.origin})"),
            DetailRow("projection", str(report.store_path)),
            DetailRow("run", report.mode.value + (" (dry run)" if report.dry_run else "")),
            DetailRow("tracked entity types", str(len(report.tracked_entity_types))),
            DetailRow("programs polled for enrollments", str(len(report.programs))),
            DetailRow("pages read", str(report.pages_read)),
        ],
        console=STDERR_CONSOLE,
    )
    if report.counts:
        render_list(
            "resources",
            [
                {
                    "type": row.resource_type,
                    "created": str(row.created),
                    "updated": str(row.updated),
                    "removed": str(row.removed),
                }
                for row in report.counts
            ],
            [
                ColumnSpec("Resource", "type", no_wrap=True),
                ColumnSpec("Created", "created", no_wrap=True),
                ColumnSpec("Updated", "updated", no_wrap=True),
                ColumnSpec("Removed", "removed", no_wrap=True),
            ],
            console=STDERR_CONSOLE,
        )
    render_list(
        "how far each collection has been read",
        [
            {
                "collection": move.endpoint.value,
                "was": "never" if move.moved_from is None else move.moved_from.isoformat(),
                "now": "never" if move.moved_to is None else move.moved_to.isoformat(),
            }
            for move in report.cursors
        ],
        [
            ColumnSpec("Collection", "collection", no_wrap=True),
            ColumnSpec("Read up to, before", "was", no_wrap=True),
            ColumnSpec("Read up to, now", "now", no_wrap=True),
        ],
        console=STDERR_CONSOLE,
    )
    if report.dry_run:
        _line(_SYNC_DRY_RUN_BANNER)
    _hint("ok", report.counts_line())
    if not report.tombstones_visible:
        _hint(
            "note",
            "this DHIS2 instance refuses the tracked entity read that includes deleted entities "
            "(BUGS.md #116); a person removed since the last run stays in the projection until an "
            "enrollment of theirs moves or the projection is rebuilt",
        )
    if report.cursor.updated_at is None:
        _hint(
            "note",
            "the projection states no cursor yet: both collections have to have been read before an "
            "answer can say what instant it is as of",
        )
    else:
        _hint("ok", f"answers served from this projection are as of {report.cursor.updated_at.isoformat()}")


#: What a sync's dry run says, so nobody reads its counts as a description of what is on disk.
_SYNC_DRY_RUN_BANNER = (
    "DRY RUN - the instance was read exactly as a committing run reads it and the counts above are "
    "what a committing run would do. Nothing was written to the projection and no cursor moved. "
    "Re-run without --dry-run to commit."
)


@app.command("sync")
def sync_command(
    directory: Annotated[
        Path, typer.Argument(file_okay=False, help="Project directory (default: current directory).")
    ] = Path("."),
    rebuild: Annotated[
        bool,
        typer.Option(
            "--rebuild",
            help="Empty the projection first, then fill it from zero. How a mapping change reaches it.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Read the instance and count what would change, writing nothing and moving no cursor.",
        ),
    ] = False,
    progress: ProgressOption = True,
) -> None:
    r"""Fill this project's materialized projection from DHIS2 - the register, as FHIR, on disk.

    A projection is a durable copy of the mapped scope of a DHIS2 instance, held as the FHIR resources
    this project's map publishes. It is what `\[serve.search] backend = "projection"` answers a register
    search from: one indexed query instead of one tracker query per key per tracked entity type, and a
    search across every value a person holds rather than an exact match on one.

    The first run reads the whole mapped scope. Every run after it reads what moved since the last one,
    which on an unchanged instance is one request and 56 bytes. `--rebuild` drops the projection and
    fills it from zero, which is routine rather than a recovery step - it is how a change to
    `\[serve.tracked_entities]` or to the published map reaches what is already stored.

    DHIS2 STAYS THE RECORD. Nothing here writes to the instance, and nothing but this command writes
    to the projection. A projection row that disagrees with DHIS2 is a defect of this command, and the
    fix for one is `--rebuild` rather than an edit.

    A deletion is followed. Every poll carries `includeDeleted=true`, which is not a flag here because
    its absence is silent: a sync without it never learns that anybody left. A tombstone removes the
    row rather than archiving a last state, because DHIS2 will not answer a read of a deleted entity.

    WHAT A SYNCED SERVER DOES NOT CHANGE. A record is still read from the instance under the
    credentials of whoever asks, so DHIS2 authorizes every disclosure exactly as it does today; the
    projection decides who is on the page. Which is why a synced answer states the instant it is as of
    and a live one does not.

    Where the projection lives is `\[serve.projection] path`, and which store holds it is
    `\[serve.projection] store` - a project that names none is refused here, naming the key.
    """
    try:
        from dhis2w_fhir_serve import SYNC_STEPS, ServeSettings
    except ImportError as error:
        raise LookupError(_serve_package_missing("sync")) from error

    from dhis2w_fhir import service

    project = load_project(directory)
    configured = project.config.serve.projection
    if not configured.enabled():
        raise CliUserError(_SYNC_NO_PROJECTION)
    generation = service.resolve_generation_profile(project)
    settings = ServeSettings(
        project_dir=project.project_root,
        live=True,
        tracked_entities=project.config.serve.tracked_entities,
        search=project.config.serve.search,
        projection=configured,
        dhis2_base_url=generation.profile.base_url,
    )
    with _progress(SYNC_STEPS, enabled=progress) as reporter:
        report = asyncio.run(_sync(settings, project, configured, rebuild=rebuild, dry_run=dry_run, reporter=reporter))
        if reporter is not None:
            reporter.finish(report.counts_line())
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
    else:
        _render_sync_report(report, generation)


#: What a project that configured no projection is told, naming the key and the two commands it pairs.
_SYNC_NO_PROJECTION = (
    'this project holds no materialized projection to fill: state `[serve.projection] store = "sqlite"` '
    'in fhir.toml, and `[serve.search] backend = "projection"` beside it if you want `d2w fhir serve` '
    "to answer register searches from it"
)


async def _sync(
    settings: ServeSettings,
    project: FhirProject,
    configured: ProjectionConfig,
    *,
    rebuild: bool,
    dry_run: bool,
    reporter: ProgressReporter | None,
) -> SyncReport:
    """Open the instance and the projection, run one sync over both, and close them again.

    The register surface comes from a live store build - the same one `d2w fhir serve --live` starts
    with - because a sync maps exactly what a live run serves, through exactly the same published map.
    A second way of deciding what a tracked entity is in FHIR would be a second answer to that
    question, and the two would disagree on the first mapping change.
    """
    from dhis2w_fhir_serve import (
        RegisterSurface,
        TrackedEntityIndex,
        build_store,
        open_live_client,
        open_projection_store,
        projection_path,
        run_sync,
    )

    async with open_live_client(project, settings) as client:
        store = await build_store(settings, project, client)
        surface = RegisterSurface.resolve(TrackedEntityIndex.from_store(project, store), settings.tracked_entities)
        async with open_projection_store(configured, project_root=project.project_root) as projection:
            if projection is None:
                raise CliUserError(_SYNC_NO_PROJECTION)
            return await run_sync(
                client,
                surface=surface,
                store=projection,
                project_root=project.project_root,
                store_path=projection_path(configured, project_root=project.project_root),
                overlap=timedelta(seconds=configured.overlap_seconds),
                rebuild=rebuild,
                dry_run=dry_run,
                narrator=reporter,
            )


@app.command("requeue")
def requeue_command(
    response_ids: Annotated[list[str] | None, typer.Argument(help="Receipt ids to move back into the queue.")] = None,
    directory: Annotated[
        Path, typer.Option("--directory", file_okay=False, help="Project directory (default: current directory).")
    ] = Path("."),
    all_rejected: Annotated[
        bool, typer.Option("--all-rejected", help="Move every receipt DHIS2 refused back into the queue.")
    ] = False,
) -> None:
    """Move receipts DHIS2 refused back into the queue, so the next forward posts them again.

    The one reverse move the spool has, and it is a decision rather than a repair: a rejection is
    DHIS2 stating that this payload is wrong, so nothing moves it back until a person who has changed
    the instance, the guide, or their mind says so.

    The import report stays in rejected/ as the record of what DHIS2 last answered about the payload.
    The next drain writes a fresh one wherever the receipt lands.

    Needs no DHIS2 connection and no profile - it is a rename inside the project directory.
    """
    from dhis2w_fhir import service

    named = list(response_ids or [])
    if not named and not all_rejected:
        raise CliUserError("name the receipt(s) to requeue, or pass --all-rejected to move every refused one")
    if named and all_rejected:
        raise CliUserError("--all-rejected moves every refused receipt, so it takes no ids of its own")
    project = load_project(directory)
    report = service.requeue_rejected_responses(project, named, all_rejected=all_rejected)
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
        return
    for receipt in report.requeued:
        _line(f"{receipt.response_id} -> {receipt.spool_path}")
    _hint("ok", report.counts_line)
    if report.requeued:
        _hint("note", "`d2w fhir forward --import` posts them again")


#: What a withdrawal's dry run closes with, once, under the counts it explains. The delete reaches
#: the real tracker endpoint under that endpoint's own validate-only mode, which for a terminal act
#: is the one rehearsal worth having.
_WITHDRAW_DRY_RUN_BANNER = (
    "DRY RUN - every delete was posted to DHIS2 under the tracker endpoint's own validate-only mode "
    "(importMode=VALIDATE). Nothing was deleted from the instance and no receipt moved. Re-run with "
    "--import to commit."
)

#: The Rich style each withdrawal outcome renders in, so a glance separates a refusal from a retraction.
_WITHDRAWAL_KIND_STYLES = {
    "retracted": "green",
    "would-retract": "yellow",
    "refused": "red",
}


def _withdrawal_kind_cell(value: Any) -> str:
    """Render one withdrawal outcome in the style it carries."""
    kind = str(value)
    return f"[{_WITHDRAWAL_KIND_STYLES.get(kind, 'default')}]{kind}[/]"


def _render_withdraw_report(report: WithdrawReport, generation: GenerationProfile) -> None:
    """Render one withdrawal run: the mode first, then a row per receipt, then what remains in DHIS2."""
    render_detail(
        "fhir withdraw",
        [
            DetailRow("profile", f"{generation.name} ({generation.origin})"),
            DetailRow("project", str(report.project_root)),
            DetailRow("mode", "DRY RUN (validate only)" if report.dry_run else "withdraw"),
            DetailRow("named", str(len(report.receipts))),
            DetailRow("refused by DHIS2", str(len(report.refused))),
        ],
        console=STDERR_CONSOLE,
    )
    render_list(
        "receipts",
        [
            {
                "id": receipt.response_id,
                "kind": receipt.kind.value,
                "event": receipt.event_uid,
                "form": receipt.questionnaire.rsplit("/", 1)[-1] or receipt.questionnaire,
                "answer": receipt.line,
            }
            for receipt in report.receipts
        ],
        [
            ColumnSpec("Receipt", "id", no_wrap=True),
            ColumnSpec("Outcome", "kind", formatter=_withdrawal_kind_cell, no_wrap=True),
            ColumnSpec("Event", "event", no_wrap=True),
            ColumnSpec("Form", "form"),
            ColumnSpec("DHIS2 said", "answer"),
        ],
    )
    if report.retracted:
        _hint(
            "note",
            "This DHIS2 instance keeps a hidden copy of each withdrawn event; none of them appears in "
            "reports any more. The UIDs are burned, so those receipts can never be forwarded again",
        )
    if report.refused:
        _hint(
            "error",
            f"{len(report.refused)} receipt(s) DHIS2 would not delete; exiting 1 - each stays in forwarded/ "
            "with the import report that says what it landed",
            style="red",
        )
    _hint("ok", report.counts_line)
    if report.dry_run:
        _hint("dry run", _WITHDRAW_DRY_RUN_BANNER, style="bold yellow")


@app.command("withdraw")
def withdraw_command(
    response_ids: Annotated[list[str], typer.Argument(help="Forwarded receipt ids to retract from DHIS2.")],
    directory: Annotated[
        Path, typer.Option("--directory", file_okay=False, help="Project directory (default: current directory).")
    ] = Path("."),
    import_responses: Annotated[
        bool,
        typer.Option(
            "--import/--dry-run",
            help="Delete the events in DHIS2 and file the receipts under withdrawn/. The default is a dry "
            "run: the delete goes to the real endpoint under its own validate-only mode, and nothing is "
            "written and nothing moves.",
        ),
    ] = False,
    withdrawals: Annotated[
        WithdrawalPosture | None,
        typer.Option(
            "--withdrawals",
            help="Whether this project retracts what it forwarded, overriding `\\[forward] withdrawals`. "
            "Off by default, and `retract` is what this command requires.",
        ),
    ] = None,
) -> None:
    r"""Retract from DHIS2 the events named forwarded receipts landed, and file each receipt as withdrawn.

    WITHDRAWAL IS TERMINAL. DHIS2 burns the UID of a tracker object it deletes and refuses it under
    every import strategy afterwards, so a withdrawn receipt can never be forwarded again. What
    remains in the instance is a hidden copy of the event carrying its values, which no ordinary read
    returns - not the nothing that the word "deleted" implies.

    DRY RUN IS THE DEFAULT. The delete goes to the real instance under the tracker endpoint's own
    validate-only mode, so DHIS2 answers whether it would take it while nothing is written; `--import`
    commits.

    `\[forward] withdrawals` gates the whole command and is off unless this project says otherwise -
    a project that publishes forms and forwards them is not thereby one that reaches back into what
    DHIS2 already holds. `--withdrawals retract` states it for one run.

    The receipt is never rewritten. Its file moves from forwarded/ to withdrawn/ with a sidecar
    holding what DHIS2 answered the delete, and the import report that recorded what it landed stays
    in forwarded/, because that document is still true of that import.

    Only a receipt in forwarded/ that landed a single event can be withdrawn, and every id is checked
    before anything is posted. `d2w data aggregate delete` and `d2w data tracker delete` are the raw
    escape hatches for the other kinds, outside the FHIR path.
    """
    from dhis2w_fhir import service

    project = load_project(directory)
    generation = service.resolve_generation_profile(project)
    report = asyncio.run(
        service.withdraw_responses(
            generation.profile,
            project,
            response_ids,
            import_responses=import_responses,
            withdrawals=withdrawals,
        )
    )
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
    else:
        _render_withdraw_report(report, generation)
    if report.refused:
        raise typer.Exit(code=1)


#: The Rich style each doctor outcome renders in, so a glance separates a break from a note.
_DOCTOR_OUTCOME_STYLES = {
    "pass": "green",
    "warn": "yellow",
    "fail": "red",
    "skipped": "dim",
    "blocked": "dim",
}


def _doctor_outcome_cell(value: Any) -> str:
    """Render one phase outcome in the style it carries."""
    outcome = str(value)
    return f"[{_DOCTOR_OUTCOME_STYLES.get(outcome, 'default')}]{outcome}[/]"


def _render_doctor_report(report: DoctorReport) -> None:
    """Render one doctor run: what it ran against, one row per phase, then every finding."""
    from dhis2w_fhir.doctor import DoctorOutcome, phase_evidence

    render_detail(
        "fhir doctor",
        [
            DetailRow("profile", f"{report.profile_name} ({report.profile_origin})"),
            DetailRow("instance", report.base_url),
            DetailRow(
                "DHIS2 version",
                f"{report.dhis2_version or 'not detected'} (plugin tree {report.version_tree or 'not bound'})",
            ),
            DetailRow(
                "workspace",
                f"{report.workspace}{'' if report.workspace_kept else ' (removed when the run ended)'}",
            ),
        ],
        console=STDERR_CONSOLE,
    )
    render_list(
        "phases",
        [
            {
                "phase": phase.phase.value,
                "outcome": phase.outcome.value,
                "seconds": f"{phase.elapsed_seconds:.1f}",
                "evidence": phase_evidence(phase),
            }
            for phase in report.phases
        ],
        [
            ColumnSpec("Phase", "phase", no_wrap=True),
            ColumnSpec("Outcome", "outcome", formatter=_doctor_outcome_cell, no_wrap=True),
            ColumnSpec("Seconds", "seconds", no_wrap=True),
            ColumnSpec("What it found", "evidence"),
        ],
        console=STDERR_CONSOLE,
    )
    findings = report.findings
    if findings:
        render_list(
            "findings",
            [
                {
                    "phase": finding.phase.value,
                    "severity": finding.severity,
                    "subject": finding.subject,
                    "where": finding.field_path or "",
                    "detail": finding.detail,
                }
                for finding in findings
            ],
            [
                ColumnSpec("Phase", "phase", no_wrap=True),
                ColumnSpec("Severity", "severity", formatter=_severity_cell, no_wrap=True),
                ColumnSpec("Subject", "subject"),
                ColumnSpec("Where", "where", no_wrap=True),
                ColumnSpec("What", "detail"),
            ],
            console=STDERR_CONSOLE,
        )
    failed = report.failed_phases
    if failed:
        _hint(
            "verdict",
            f"{report.verdict_line}; {', '.join(phase.phase.value for phase in failed)} failed - "
            "this instance breaks the toolchain as configured",
            style="bold red",
        )
    elif any(phase.outcome is DoctorOutcome.WARNED for phase in report.phases):
        _hint("verdict", f"{report.verdict_line}; the toolchain runs, with notes", style="yellow")
    else:
        _hint("verdict", f"{report.verdict_line}; the toolchain runs clean against this instance", style="green")


def _write_doctor_report(report: DoctorReport) -> Path:
    """Write one run's markdown report where a handover reads it, and say where that is."""
    from dhis2w_fhir import REPORTS_DIRECTORY
    from dhis2w_fhir.doctor import DOCTOR_REPORT_STEM, render_doctor_markdown

    root = report.workspace if report.options.workspace is not None else Path.cwd()
    directory = root / REPORTS_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{DOCTOR_REPORT_STEM}.md"
    destination.write_text(render_doctor_markdown(report), encoding="utf-8")
    return destination


@app.command("doctor")
def doctor_command(
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="DHIS2 profile to run against, ahead of DHIS2_PROFILE and any nearby project.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            file_okay=False,
            help="Directory to run in, kept after the run. The default is a temporary directory, "
            "removed when the run ends unless --keep says otherwise.",
        ),
    ] = None,
    keep: Annotated[
        bool,
        typer.Option("--keep", help="Keep the temporary workspace, so the generated project can be read afterwards."),
    ] = False,
    all_targets: Annotated[
        bool,
        typer.Option(
            "--all-targets",
            help="Scaffold empty selection tables, which takes every data set, every program, and every "
            "organisation-unit level. The default is a small representative probe.",
        ),
    ] = False,
    live: Annotated[
        bool,
        typer.Option(
            "--live",
            help="Run the oracle phase: fetch the DHIS2 objects behind a sample of the served resources "
            "and let the instance judge whether each one still derives from current instance state.",
        ),
    ] = False,
    samples: Annotated[
        int,
        typer.Option("--samples", min=0, help="How many resources per family the oracle deep-compares."),
    ] = DEFAULT_ORACLE_SAMPLES,
    progress: ProgressOption = True,
) -> None:
    """Run the whole FHIR toolchain against this profile's instance and report what the instance breaks.

    Ten phases: connect, scaffold, generate, compile, validate, serve, capture, forward, oracle,
    drift. Each reports pass, warn, fail, skipped, or blocked with its reason. The first nine run in
    a throwaway workspace; drift reads the published guide the working directory sits in.

    The instance comes from `--profile/-p`, then `d2w -p <name>`, then `DHIS2_PROFILE`, then the
    `fhir.toml` of a nearby project - the resolution `d2w fhir validate` runs on the same subject.

    A phase that fails never stops one that does not depend on it, and only a failure exits 1.

    Compiling needs a FSH compiler on the machine; without one the phase is skipped and the served
    store is built by the live builders instead, so every later phase still runs.

    `--live` adds the oracle: the DHIS2 objects behind a seeded sample of the served resources are
    fetched back and the instance decides whether the served output still derives from them.

    The drift phase asks the other question: run from a project directory, it names every
    organisation unit, option, question, and program stage the instance holds inside that project's
    own selection that the published guide does not. Drift is a warning - the guide is out of date
    rather than broken - so it never exits 1.

    The run writes reports/fhir-doctor-report.md, into the workspace when one was named and into the
    working directory otherwise.
    """
    from dhis2w_fhir.doctor import DOCTOR_STEPS, DoctorOptions, resolve_doctor_profile, run_doctor

    generation = resolve_doctor_profile(profile)
    options = DoctorOptions(
        workspace=workspace,
        keep=keep,
        all_targets=all_targets,
        live=live,
        samples=samples,
    )
    with _progress(DOCTOR_STEPS, enabled=progress) as reporter:
        report = asyncio.run(run_doctor(generation, options, reporter=reporter))
        if reporter is not None:
            reporter.finish(report.verdict_line)
    destination = _write_doctor_report(report)
    if is_json_output():
        typer.echo(report.model_dump_json(indent=2))
    else:
        _line(f"wrote {destination}")
        _render_doctor_report(report)
    if report.failed_phases:
        raise typer.Exit(code=1)


def register(root_app: Any) -> None:
    """Mount this plugin's Typer sub-app under `d2w fhir`."""
    root_app.add_typer(app, name="fhir", help="FHIR Implementation Guide generation from DHIS2 metadata.")
