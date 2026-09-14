"""Scaffolding a guide and the organisation-unit registry package it depends on, in one command.

The two projects have to agree about four things - the package id, its canonical, the guide's own,
and the path between them - and a disagreement surfaces late and indirectly. So the point of these
tests is not that two directories appear: it is that everything the two share is derived from one
identity and cannot drift apart.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from dhis2w_cli.main import build_app
from dhis2w_fhir.config import load_project
from dhis2w_fhir.scaffold import (
    GUIDE_RELATIVE_ROOT,
    REGISTRY_RELATIVE_ROOT,
    build_guide_and_registry_files,
    build_scaffold_files,
)
from dhis2w_fhir.scaffold.refresh import refresh_project
from dhis2w_fhir.scaffold.schemas import InitOptions
from typer.testing import CliRunner

_runner = CliRunner()

_OPTIONS = InitOptions(
    ig_id="dhis2.fhir.hmis",
    canonical="http://hmis.example.org/fhir",
    name="Hmis",
    title="HMIS Implementation Guide",
    publisher="Example Org",
    profile="myserver",
    max_level=3,
    data_set_ids=["BfMAe6Itzgt"],
)


def _by_path(options: InitOptions = _OPTIONS) -> dict[str, str]:
    """Both projects plus the two root files, indexed by path under the directory that holds them."""
    return {f.relative_path: f.content for f in build_guide_and_registry_files(options, copyright_year=2026)}


def _restate(directory: Path, *, title: str | None = None, canonical: str | None = None) -> None:
    """Rename the guide in its own `fhir.toml`, which is where a refresh reads the pair's identity."""
    config = directory / GUIDE_RELATIVE_ROOT / "fhir.toml"
    text = config.read_text(encoding="utf-8")
    if title is not None:
        text = text.replace(f'title = "{_OPTIONS.title}"', f'title = "{title}"', 1)
    if canonical is not None:
        text = text.replace(f'canonical = "{_OPTIONS.canonical}"', f'canonical = "{canonical}"', 1)
    config.write_text(text, encoding="utf-8")


def _write(directory: Path, options: InitOptions = _OPTIONS) -> Path:
    """Lay both projects down on disk, as `d2w fhir init --with-registry` does."""
    for scaffold_file in build_guide_and_registry_files(options, copyright_year=2026):
        destination = directory / scaffold_file.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(scaffold_file.content, encoding="utf-8")
    return directory


# --- what makes the two agree --------------------------------------------------------------------


def test_both_projects_land_under_one_directory_and_load(tmp_path: Path) -> None:
    """Two projects, one parent - and each is an ordinary project the loader accepts."""
    _write(tmp_path)

    registry = load_project(tmp_path / REGISTRY_RELATIVE_ROOT).config
    guide = load_project(tmp_path / GUIDE_RELATIVE_ROOT).config

    assert registry.publishes_organisation_units is True
    assert guide.is_package_project is False
    assert guide.registry_dependency is not None


def test_the_identity_the_two_share_is_derived_from_one(tmp_path: Path) -> None:
    """The guide's dependency names exactly what the registry publishes, because both come from --id."""
    _write(tmp_path)
    registry = load_project(tmp_path / REGISTRY_RELATIVE_ROOT).config
    guide = load_project(tmp_path / GUIDE_RELATIVE_ROOT).config
    dependency = guide.registry_dependency
    assert dependency is not None

    assert dependency.id == registry.ig.id == "dhis2.fhir.hmis.registry"
    assert dependency.canonical == registry.ig.canonical == "http://hmis.example.org/fhir/registry"
    assert guide.ig.id == "dhis2.fhir.hmis"
    assert guide.ig.canonical == "http://hmis.example.org/fhir"


def test_the_path_between_them_resolves_to_the_registry_beside_the_guide(tmp_path: Path) -> None:
    """`path` is what the facade, the forward and the artifact check all read the registry through."""
    from dhis2w_fhir.registry_package import resolve_registry_source

    _write(tmp_path)
    registry_resources = tmp_path / REGISTRY_RELATIVE_ROOT / "ig" / "input" / "resources" / "registry"
    registry_resources.mkdir(parents=True, exist_ok=True)
    (registry_resources / "Location-x.json").write_text('{"resourceType": "Location", "id": "x"}', encoding="utf-8")

    source = resolve_registry_source(load_project(tmp_path / GUIDE_RELATIVE_ROOT))

    assert source is not None
    assert source.kind == "checkout"
    assert source.location == registry_resources.resolve()


def test_the_level_cap_reaches_both_because_they_must_mean_the_same_units(tmp_path: Path) -> None:
    """The guide's selection says which units its forms may name; the registry's says which exist."""
    _write(tmp_path)

    registry = load_project(tmp_path / REGISTRY_RELATIVE_ROOT).config
    guide = load_project(tmp_path / GUIDE_RELATIVE_ROOT).config

    assert registry.generate.organisation_units.max_level == 3
    assert guide.generate.organisation_units.max_level == 3


def test_the_selection_goes_to_the_guide_and_the_package_keeps_none(tmp_path: Path) -> None:
    """A package publishing a data set is refused when its fhir.toml loads, so it is never given one."""
    _write(tmp_path)
    registry = tomllib.loads((tmp_path / REGISTRY_RELATIVE_ROOT / "fhir.toml").read_text(encoding="utf-8"))
    guide = tomllib.loads((tmp_path / GUIDE_RELATIVE_ROOT / "fhir.toml").read_text(encoding="utf-8"))

    assert "data_sets" not in registry["generate"]
    assert registry["ig"]["kind"] == "package"
    assert registry["ig"]["publishes"] == "organisation-units"
    assert guide["generate"]["data_sets"]["include_ids"] == ["BfMAe6Itzgt"]
    assert "publishes" not in guide["ig"]


def test_the_guide_scaffold_carries_the_dependency_into_sushi_and_the_makefile() -> None:
    """Naming the registry in fhir.toml is only half of it; the build has to install the package."""
    files = _by_path()

    sushi = yaml.safe_load(files[f"{GUIDE_RELATIVE_ROOT}/ig/sushi-config.yaml"])
    assert sushi["dependencies"] == {
        "dhis2.fhir.hmis.registry": {
            "uri": "http://hmis.example.org/fhir/registry/ImplementationGuide/dhis2.fhir.hmis.registry",
            "version": "0.1.0",
        }
    }
    guide_makefile = files[f"{GUIDE_RELATIVE_ROOT}/Makefile"]
    assert "REGISTRY_TGZ ?= ../registry/ig/output/package.tgz" in guide_makefile
    assert "build: cache-init registry-install" in guide_makefile


def test_the_root_makefile_builds_the_registry_before_the_guide() -> None:
    """The order is the one thing a reader must not get wrong, so the target states it."""
    root = _by_path()["Makefile"]

    assert "build: build-registry build-guide" in root
    assert root.index("build-registry:") < root.index("build-guide:")
    assert "$(FORWARD_HEAP)" in root
    # Empty unless you set it: an empty override passed down would beat each project's own
    # derived default and leave the publisher with no -Xmx at all.
    assert "FORWARD_HEAP = $(if $(JAVA_HEAP),JAVA_HEAP=$(JAVA_HEAP))" in root


def test_clean_all_reaches_both_terminology_caches() -> None:
    """Each project keeps its own ig/input-cache, and only that project's own clean-all removes it.

    Giving the guide `clean` here left several megabytes behind that a reader had asked to be gone,
    which only shows up when someone measures the directory before sharing it.
    """
    clean_all = _by_path()["Makefile"].split("clean-all:", 1)[1]

    assert "$(REGISTRY)) clean-all" in clean_all
    assert "$(GUIDE)) clean-all" in clean_all
    # `clean` would leave that project's ig/input-cache behind, which is the bug this pins.
    assert "$(GUIDE)) clean\n" not in clean_all


def test_a_plain_init_is_untouched_by_any_of_this() -> None:
    """The flag is opt-in: one project scaffolds exactly what it scaffolded before."""
    alone = {f.relative_path for f in build_scaffold_files(_OPTIONS, copyright_year=2026)}
    assert "Makefile" in alone
    assert "README.md" not in alone
    assert not any(path.startswith((f"{GUIDE_RELATIVE_ROOT}/", f"{REGISTRY_RELATIVE_ROOT}/")) for path in alone)


# --- refresh ---------------------------------------------------------------------------------------


def test_a_refresh_of_the_directory_refreshes_both_projects_and_the_makefile(tmp_path: Path) -> None:
    """The root Makefile belongs to no project's fhir.toml, so nothing else would keep it current."""
    _write(tmp_path)
    (tmp_path / "Makefile").write_text("# replaced by hand\n", encoding="utf-8")

    report = refresh_project(tmp_path)

    assert "Makefile" in report.refreshed_files
    assert "build: build-registry build-guide" in (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert report.diverged_files == []
    # Both projects were visited, and their paths are reported under the directory each occupies.
    assert any(path.startswith(f"{REGISTRY_RELATIVE_ROOT}/") for path in report.unchanged_files)
    assert any(path.startswith(f"{GUIDE_RELATIVE_ROOT}/") for path in report.unchanged_files)


def test_a_refresh_with_nothing_changed_writes_nothing(tmp_path: Path) -> None:
    """Idempotence is what makes a refresh safe to run, and what a drifting file would break."""
    _write(tmp_path)

    report = refresh_project(tmp_path)

    assert report.refreshed_files == []
    assert report.created_files == []
    assert report.diverged_files == []


def test_a_refresh_keeps_a_paragraph_the_reader_added_to_the_readme(tmp_path: Path) -> None:
    """The README is prose, so a deployment note written into it is what a refresh is there to keep."""
    _write(tmp_path)
    readme = tmp_path / "README.md"
    extended = readme.read_text(encoding="utf-8") + "\nDeployment instructions added by the user.\n"
    readme.write_text(extended, encoding="utf-8")

    report = refresh_project(tmp_path)

    assert report.extended_files == ["README.md"]
    assert report.refreshed_files == []
    assert readme.read_text(encoding="utf-8") == extended


def test_a_refresh_keeps_a_readme_whose_scaffold_line_was_rewritten(tmp_path: Path) -> None:
    """A line the current scaffold does not write names no author, so the reader's version stays."""
    _write(tmp_path)
    readme = tmp_path / "README.md"
    rendered = readme.read_text(encoding="utf-8")
    edited = rendered.replace("## Sizing the registry", "## How deep we publish", 1)
    assert edited != rendered
    readme.write_text(edited, encoding="utf-8")

    report = refresh_project(tmp_path)

    assert report.diverged_files == ["README.md"]
    assert readme.read_text(encoding="utf-8") == edited


def test_a_refresh_writes_a_readme_the_current_scaffold_carries_whole(tmp_path: Path) -> None:
    """A README holding nothing of its own is rewritten, so the scaffold's own additions land."""
    _write(tmp_path)
    readme = tmp_path / "README.md"
    rendered = readme.read_text(encoding="utf-8")
    stale = rendered.split("## Sizing the registry", 1)[0]
    readme.write_text(stale, encoding="utf-8")

    report = refresh_project(tmp_path)

    assert report.refreshed_files == ["README.md"]
    assert readme.read_text(encoding="utf-8") == rendered


def test_a_refresh_writes_the_renamed_title_onto_a_pristine_readme(tmp_path: Path) -> None:
    """The pair's cover carries the guide's title, which `fhir.toml` declares and the reader does not."""
    _write(tmp_path)
    readme = tmp_path / "README.md"
    assert readme.read_text(encoding="utf-8").startswith(f"# {_OPTIONS.title}\n")
    _restate(tmp_path, title="National HMIS Implementation Guide")

    report = refresh_project(tmp_path)

    assert "README.md" in report.refreshed_files
    assert report.diverged_files == []
    assert readme.read_text(encoding="utf-8").startswith("# National HMIS Implementation Guide\n")


def test_a_refresh_writes_the_renamed_title_onto_a_readme_the_reader_added_to(tmp_path: Path) -> None:
    """One rename lands on the cover of a README that also carries the reader's own prose."""
    _write(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nDeployment instructions added by the user.\n")
    _restate(tmp_path, title="National HMIS Implementation Guide")

    report = refresh_project(tmp_path)

    assert "README.md" in report.refreshed_files
    assert report.diverged_files == []
    refreshed = readme.read_text(encoding="utf-8")
    assert refreshed.startswith("# National HMIS Implementation Guide\n")
    assert refreshed.endswith("Deployment instructions added by the user.\n")


def test_a_refresh_writes_the_renamed_registry_canonical_onto_the_readme(tmp_path: Path) -> None:
    """The README documents the canonical every unit reference sits under, so a rename has to reach it."""
    _write(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nDeployment instructions added by the user.\n")
    _restate(tmp_path, canonical="http://national.example.org/fhir")

    report = refresh_project(tmp_path)

    assert "README.md" in report.refreshed_files
    assert report.diverged_files == []
    refreshed = readme.read_text(encoding="utf-8")
    assert "The package's canonical is `http://national.example.org/fhir/registry`." in refreshed
    assert _OPTIONS.canonical not in refreshed
    assert refreshed.endswith("Deployment instructions added by the user.\n")


def test_a_refresh_rewrites_the_root_makefile_line_a_reader_edited(tmp_path: Path) -> None:
    """Every knob the root Makefile has is a `?=` default set outside the file, so it lands whole."""
    _write(tmp_path)
    makefile = tmp_path / "Makefile"
    rendered = makefile.read_text(encoding="utf-8")
    makefile.write_text(rendered.replace("D2W ?= uv run d2w", "D2W ?= uv run --project /elsewhere d2w", 1))

    report = refresh_project(tmp_path)

    assert "Makefile" in report.refreshed_files
    assert makefile.read_text(encoding="utf-8") == rendered


# --- the order the root Makefile keeps under -j ---------------------------------------------------

#: A registry build that takes long enough for a guide started beside it to be running while it does.
_REGISTRY_STUB = """generate:
\t@true

build:
\t@sleep 1
\t@touch ../registry-ready
"""

#: A guide build that fails unless the registry finished first, which is the ordering under test.
_GUIDE_STUB = """generate:
\t@true

build:
\t@test -f ../registry-ready || { echo "the guide started before the registry finished"; exit 1; }
"""


@pytest.mark.skipif(shutil.which("make") is None, reason="the ordering is a property of make itself")
@pytest.mark.parametrize("target", ["build", "all"])
def test_the_root_makefile_builds_the_registry_first_under_parallel_make(tmp_path: Path, target: str) -> None:
    """A guide built beside the registry has a dependency the publisher cannot resolve, so -j must not.

    The two child projects stand in for the real builds: the registry sleeps and leaves a marker, and
    the guide fails unless the marker is there. Any run that starts them together fails the guide.
    """
    (tmp_path / "Makefile").write_text(_by_path()["Makefile"], encoding="utf-8")
    (tmp_path / REGISTRY_RELATIVE_ROOT).mkdir()
    (tmp_path / REGISTRY_RELATIVE_ROOT / "Makefile").write_text(_REGISTRY_STUB, encoding="utf-8")
    (tmp_path / GUIDE_RELATIVE_ROOT).mkdir()
    (tmp_path / GUIDE_RELATIVE_ROOT / "Makefile").write_text(_GUIDE_STUB, encoding="utf-8")
    environment = {key: value for key, value in os.environ.items() if key != "MAKEFLAGS"}

    result = subprocess.run(
        ["make", "-j2", target],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


# --- the command and its refusals --------------------------------------------------------------------


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run in an empty temporary working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_command_scaffolds_both_and_says_which_builds_first(workdir: Path) -> None:
    """One command, two wired projects, and a closing line naming the order."""
    result = _runner.invoke(
        build_app(),
        ["fhir", "init", "hmis", "--with-registry", "--id", "dhis2.fhir.hmis", "--canonical", "http://x.example/fhir"],
    )

    assert result.exit_code == 0, result.output
    assert (workdir / "hmis" / REGISTRY_RELATIVE_ROOT / "fhir.toml").is_file()
    assert (workdir / "hmis" / GUIDE_RELATIVE_ROOT / "fhir.toml").is_file()
    assert (workdir / "hmis" / "Makefile").is_file()
    assert "the registry builds first" in " ".join(result.output.split())


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        (["--publishes", "organisation-units"], "scaffolds that package alone"),
        (["--template", "aggregate-minimal"], "scaffolds two"),
        (["--registry-id", "x"], "cannot disagree"),
        (["--registry-canonical", "http://x"], "cannot disagree"),
        (["--registry-path", "../elsewhere"], "cannot disagree"),
    ],
)
def test_flags_the_derivation_would_contradict_are_refused(workdir: Path, arguments: list[str], fragment: str) -> None:
    """Each refusal names what to drop, because silently ignoring a stated flag is worse."""
    result = _runner.invoke(build_app(), ["fhir", "init", "hmis", "--with-registry", *arguments])

    assert result.exit_code != 0
    assert fragment in " ".join(result.output.replace("│", " ").split())
    assert not (workdir / "hmis").exists()


def test_a_refresh_carrying_the_flag_is_refused(workdir: Path) -> None:
    """A refresh reads the projects on disk, so a scaffold flag beside it could not land."""
    result = _runner.invoke(build_app(), ["fhir", "init", ".", "--refresh", "--with-registry"])

    assert result.exit_code != 0
    assert "--with-registry" in " ".join(result.output.replace("│", " ").split())
