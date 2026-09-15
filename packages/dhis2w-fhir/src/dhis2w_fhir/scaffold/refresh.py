"""Bring an existing project's scaffold-managed files up to date without dropping anything the user wrote.

The scaffold grows: a `path-resource` declaration lands in `ig/sushi-config.yaml`, an entry lands in
`.gitignore`, a recipe in the `Makefile` takes a new shape, and a project scaffolded before any of
that carries none of it. `refresh_project` re-renders the scaffold for that project - identity read
back off disk, not defaults - and lands the current render wherever nothing of the project's own is
at stake.

The files at `OWNED_WHOLE_RELATIVE_PATHS` are the scaffold's outright: the `Makefile`, the
`Dockerfile`, `.python-version`, `ig/ig.ini` and `ig/fsh.ini` hold no value that is the reader's to
keep, because each is either a `?=` default taken from the command line or the environment, or a
value the project states elsewhere and the render carries back in. A refresh writes each of those
from the current render whenever it differs, so a revision that replaces a line lands whole - and
an edit written into one of those five files does not survive it, which is why the report gives
them the verdict `rewritten` of their own rather than the `refreshed` that means every line on disk
is still there.

Every other file goes through the line ladder. It is rewritten only when the render reproduces every
line already there, so a refresh adds what the scaffold gained and never takes away what the user
added. A file holding a line the scaffold would not produce stays exactly as it is and is reported -
as carrying the user's additions when it still holds every current scaffold line, and as diverged
when lines are missing in both directions, since the user's edits and a scaffold line that has since
changed read identically from disk. `fhir.toml` is the user's configuration and is never written at
all.

`fhir.example.toml` takes the ladder on its settings lines alone. It is the catalogue of every key a
project may set, and the sentences explaining those keys are re-worded release by release, so a
project scaffolded by an older release carries pages of prose the current render does not produce
and nothing of anybody's own. Grading it on the TOML - the table headers, the keys and the values a
reader copies into `fhir.toml` - is what tells those two apart: a file whose settings the current
render reproduces is a render of this scaffold under some release's wording, so the current render
lands and the verdict is `refreshed`, while one carrying a setting the render does not produce is a
divergence and is kept. The prose is the scaffold's, and a comment written into that file does not
survive a refresh.

A directory holding both projects of a split guide carries two files of its own, and both take
the same two rules: the `Makefile` that drives the two projects is named in
`OWNED_WHOLE_RELATIVE_PATHS` like any other and is rewritten whole, and the `README.md` beside it goes
through the line ladder, so prose written under the scaffold's own sections stays. Two lines of
that README are the guide's identity rather than the reader's - the title on its cover and the
registry canonical it names - so they are owned lines like the front page's heading, and a rename
in the guide's `fhir.toml` lands on both while the prose around them is kept.

A file can be both written and kept at once: an identity line lands on it while it goes on holding
lines the render does not produce. That is its own verdict - `refreshed, with your additions` - so a
person who appended a section to the front page and then renamed the guide reads that both happened,
rather than reading `refreshed` and having to open the file to find out whether their section is
still there.

The identity lines are the exception to line preservation, because `fhir.toml` declares them. Five
files carry the identity in every project - `ig/sushi-config.yaml`, `fhir.example.toml`, the front
page at `ig/input/pagecontent/index.md`, `ig/ig.ini`, and `pyproject.toml`, joined by the pair's
`README.md` where there is one - and each owns the lines listed in
`dhis2w_fhir.scaffold.identity`, so a refresh substitutes each of them into the file and reports it
refreshed. Every other line of every one of those files is the project's and survives
byte-identical.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from dhis2w_fhir.config import FHIR_CONFIG_FILENAME, NoFhirProjectError, load_fhir_config
from dhis2w_fhir.scaffold import (
    CONFIG_EXAMPLE_RELATIVE_PATH,
    FSH_INI_RELATIVE_PATH,
    GUIDE_RELATIVE_ROOT,
    OWNED_WHOLE_RELATIVE_PATHS,
    REGISTRY_RELATIVE_ROOT,
    SUSHI_CONFIG_RELATIVE_PATH,
    build_guide_and_registry_files,
    build_scaffold_files,
)
from dhis2w_fhir.scaffold.identity import adopt_scaffold_owned_lines
from dhis2w_fhir.scaffold.schemas import (
    DEFAULT_SUSHI_TIMEOUT_SECONDS,
    InitOptions,
    ProjectScaffoldState,
    ScaffoldFile,
    ScaffoldReport,
)

__all__ = ["preserves_every_line", "read_project_scaffold_state", "refresh_project", "settings_lines"]

#: The files whose comment prose is the scaffold's own documentation rather than anything a reader
#: wrote. `fhir.example.toml` is the catalogue of every key a project may set: its settings lines are
#: a reader's - they are what gets copied into `fhir.toml`, and one changed or added is a divergence
#: the ladder keeps - while the sentences explaining each key are re-worded release by release. So
#: the ladder compares these files on their settings lines alone, and a file whose settings the
#: current render reproduces is a render of this scaffold under some release's prose: the current
#: render lands, and the verdict is `refreshed`. A comment written into one does not survive that.
_PROSE_OWNED_RELATIVE_PATHS = (CONFIG_EXAMPLE_RELATIVE_PATH,)

#: What a project may carry from an older scaffold, and the file that writes that content today.
_SUPERSEDED_FILES = {"fhir.toml.example": CONFIG_EXAMPLE_RELATIVE_PATH}

#: `copyrightYear: 2026+` of sushi-config - the scaffold stamps the year it ran and nothing else records it.
_COPYRIGHT_YEAR_PATTERN = re.compile(r"^copyrightYear:\s*(\d{4})\+?\s*$", re.MULTILINE)

#: The publisher home page of sushi-config, the scaffold's only two-space `url:` key.
_PUBLISHER_URL_PATTERN = re.compile(r"^  url:\s*(\S+)\s*$", re.MULTILINE)

#: The `[FSH] timeout` of fsh.ini, the ceiling the IG publisher gives its internal SUSHI run.
_SUSHI_TIMEOUT_PATTERN = re.compile(r"^timeout\s*=\s*(\d+)\s*$", re.MULTILINE)


def read_project_scaffold_state(directory: Path) -> ProjectScaffoldState:
    """Recover the scaffold inputs of the project in `directory` from its fhir.toml, sushi-config, and fsh.ini."""
    config_path = directory / FHIR_CONFIG_FILENAME
    if not config_path.is_file():
        raise NoFhirProjectError(
            f"no {FHIR_CONFIG_FILENAME} in {directory} - there is no project to refresh. "
            f"Run `d2w fhir init {directory}` to scaffold one."
        )
    config = load_fhir_config(config_path)
    sushi_config = _read_text(directory / SUSHI_CONFIG_RELATIVE_PATH)
    fsh_ini = _read_text(directory / FSH_INI_RELATIVE_PATH)
    copyright_year = _COPYRIGHT_YEAR_PATTERN.search(sushi_config)
    publisher_url = _PUBLISHER_URL_PATTERN.search(sushi_config)
    sushi_timeout = _SUSHI_TIMEOUT_PATTERN.search(fsh_ini)
    options = InitOptions(
        ig_id=config.ig.id,
        canonical=config.ig.canonical,
        name=config.ig.name,
        title=config.ig.title,
        publisher=config.ig.publisher,
        status=config.ig.status,
        publisher_url=publisher_url.group(1) if publisher_url else None,
        profile=config.profile,
        sushi_timeout=int(sushi_timeout.group(1)) if sushi_timeout else DEFAULT_SUSHI_TIMEOUT_SECONDS,
        identifier_system_base=config.generate.identifier_system_base,
        max_level=config.generate.organisation_units.max_level,
        data_set_ids=list(config.generate.data_sets.include_ids),
        event_program_ids=list(config.generate.event_programs.include_ids),
        tracker_program_ids=list(config.generate.tracker_programs.include_ids),
        kind=config.ig.kind,
        publishes=config.ig.publishes,
        registry=config.registry_dependency,
    )
    year = int(copyright_year.group(1)) if copyright_year else datetime.now(tz=UTC).year
    return ProjectScaffoldState(options=options, copyright_year=year)


def _holds_guide_and_registry(directory: Path) -> bool:
    """Whether this directory is the root of a split guide rather than a project itself."""
    if (directory / FHIR_CONFIG_FILENAME).is_file():
        return False
    return all(
        (directory / root / FHIR_CONFIG_FILENAME).is_file() for root in (REGISTRY_RELATIVE_ROOT, GUIDE_RELATIVE_ROOT)
    )


def _refresh_guide_and_registry(directory: Path) -> ScaffoldReport:
    """Refresh both projects of a split guide and the two files the directory itself holds.

    Each project refreshes exactly as it would on its own - its `fhir.toml` is what its render is
    derived from, and neither is written. The two root files have no `fhir.toml` of their own, so
    they are re-rendered from the guide's recovered inputs and land on the same two rules every
    other file takes: the `Makefile` that drives the two projects is the scaffold's outright and is
    rewritten whole whenever it differs, and the `README.md` beside it goes through the line ladder,
    so a paragraph written under the scaffold's sections is reported and kept rather than replaced.
    """
    report = ScaffoldReport(directory=directory.resolve())
    for root in (REGISTRY_RELATIVE_ROOT, GUIDE_RELATIVE_ROOT):
        nested = refresh_project(directory / root)
        for field in (
            "created_files",
            "rewritten_files",
            "refreshed_files",
            "refreshed_with_additions_files",
            "unchanged_files",
            "extended_files",
            "diverged_files",
        ):
            getattr(report, field).extend(f"{root}/{path}" for path in getattr(nested, field))
        report.notes.extend(nested.notes)
    state = read_project_scaffold_state(directory / GUIDE_RELATIVE_ROOT)
    for scaffold_file in build_guide_and_registry_files(state.options, copyright_year=state.copyright_year):
        if "/" in scaffold_file.relative_path:
            continue
        _land_scaffold_file(directory / scaffold_file.relative_path, scaffold_file, report)
    return report


def preserves_every_line(current: str, rendered: str) -> bool:
    """Report whether `rendered` carries every line of `current`, in order - rewriting loses nothing."""
    remaining = iter(rendered.splitlines())
    return all(any(candidate == line for candidate in remaining) for line in current.splitlines())


def settings_lines(text: str) -> str:
    """The TOML of a document with its comment prose and blank lines dropped - what a reader sets.

    A table header, a key, and a value are the file's settings; a `#` line is the scaffold's prose
    about them. Reading a prose-owned file through this is what lets a refresh tell a render of an
    older release from an edit somebody made.
    """
    kept = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return "\n".join(kept)


def _comparable_lines(relative_path: str, text: str) -> str:
    """One file as the line ladder grades it: its settings alone where the scaffold owns the prose."""
    return settings_lines(text) if relative_path in _PROSE_OWNED_RELATIVE_PATHS else text


def refresh_project(directory: Path) -> ScaffoldReport:
    """Re-render the scaffold for the project in `directory`, landing every file nothing of the project's is in.

    A directory holding no `fhir.toml` of its own but holding both projects of a split guide is
    refreshed as those two plus the Makefile that drives them, so the file nobody's `fhir.toml`
    describes cannot drift while the projects beneath it stay current.
    """
    if _holds_guide_and_registry(directory):
        return _refresh_guide_and_registry(directory)
    state = read_project_scaffold_state(directory)
    report = ScaffoldReport(directory=directory.resolve())
    for scaffold_file in build_scaffold_files(state.options, copyright_year=state.copyright_year):
        relative_path = scaffold_file.relative_path
        if relative_path == FHIR_CONFIG_FILENAME:
            continue
        _land_scaffold_file(directory / relative_path, scaffold_file, report)
    report.notes.extend(_files_the_scaffold_no_longer_writes(directory))
    return report


def _land_scaffold_file(destination: Path, scaffold_file: ScaffoldFile, report: ScaffoldReport) -> None:
    """Land one rendered file where nothing of the project's own is at stake, and report what it got."""
    relative_path = scaffold_file.relative_path
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(scaffold_file.content, encoding="utf-8")
        report.created_files.append(relative_path)
        return
    current = _read_file(destination)
    if current is None:
        report.diverged_files.append(relative_path)
        return
    if current == scaffold_file.content:
        report.unchanged_files.append(relative_path)
        return
    if relative_path in OWNED_WHOLE_RELATIVE_PATHS:
        # The scaffold's own toolchain file: the render lands whole, replacing whatever line stood
        # there. Its own verdict, because `refreshed` means a rewrite that kept every line on disk.
        destination.write_text(scaffold_file.content, encoding="utf-8")
        report.rewritten_files.append(relative_path)
        return
    comparable = adopt_scaffold_owned_lines(relative_path, current, scaffold_file.content)
    graded = _comparable_lines(relative_path, comparable)
    rendered = _comparable_lines(relative_path, scaffold_file.content)
    if preserves_every_line(graded, rendered):
        destination.write_text(scaffold_file.content, encoding="utf-8")
        report.refreshed_files.append(relative_path)
    elif comparable != current:
        # The identity fhir.toml declares lands on its own lines, and every other line the
        # project wrote - its own additions included - stays exactly where it is. A file that
        # still carries every current scaffold line on top of that is both written and kept, and
        # the verdict says both: a reader learns their own lines survived the write.
        destination.write_text(comparable, encoding="utf-8")
        if preserves_every_line(rendered, graded):
            report.refreshed_with_additions_files.append(relative_path)
        else:
            report.refreshed_files.append(relative_path)
    elif preserves_every_line(rendered, graded):
        # The file holds every line the current render produces, plus lines of its own:
        # user additions on a current scaffold, with nothing for a refresh to add.
        report.extended_files.append(relative_path)
    else:
        # Lines missing in both directions. The user's edits and a scaffold line that has
        # since changed read identically here, so the verdict claims neither author.
        report.diverged_files.append(relative_path)


def _files_the_scaffold_no_longer_writes(directory: Path) -> list[str]:
    """Name each file a project carries that the scaffold does not write, so the person can delete it."""
    return [
        f"{superseded} is not a scaffold file; delete it, {replacement} has replaced it"
        for superseded, replacement in _SUPERSEDED_FILES.items()
        if (directory / superseded).exists()
    ]


def _read_file(path: Path) -> str | None:
    """Read a project file, returning None when it cannot be read as text - unreadable content is never replaced."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_text(path: Path) -> str:
    """Read a project file for value recovery, treating an absent or unreadable one as empty."""
    return _read_file(path) or ""
