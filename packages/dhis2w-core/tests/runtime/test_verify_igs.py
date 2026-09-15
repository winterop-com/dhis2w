"""Unit tests for `infra/scripts/verify_igs.py`, the example IG catalog verifier."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "infra" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from verify_igs import (  # noqa: E402 - path-prepend intentional
    IGS_ROOT,
    REFUSING_PROJECTS,
    check_refusal_leftovers,
    discover_projects,
)


def _refused_project(root: Path) -> Path:
    """A project tree shaped like the one a refused `d2w fhir generate` leaves: aliases plus foundation."""
    fsh = root / "ig" / "input" / "fsh"
    (fsh / "foundation").mkdir(parents=True)
    (fsh / "aliases.fsh").write_text("Alias: $d2 = http://example.org\n")
    (fsh / "foundation" / "d2-organisation-unit.fsh").write_text("Profile: D2OrganisationUnit\n")
    return root


def test_the_exhibit_passes_on_the_foundation_target_the_refusal_leaves(tmp_path: Path) -> None:
    """A refused run writes the foundation target and stops there, which is what the step reads."""
    outcome = check_refusal_leftovers(_refused_project(tmp_path))

    assert outcome.status == "PASS"
    assert "foundation target alone (1 .fsh)" in outcome.detail


def test_the_exhibit_fails_where_the_refused_run_wrote_past_the_foundation_target(tmp_path: Path) -> None:
    """A refusal that let a form target write is a refusal that came too late, and the catalog says which."""
    project = _refused_project(tmp_path)
    (project / "ig" / "input" / "fsh" / "questionnaires").mkdir()

    outcome = check_refusal_leftovers(project)

    assert outcome.status == "FAIL"
    assert "ig/input/fsh/questionnaires" in outcome.detail


def test_the_exhibit_fails_where_nothing_was_written_at_all(tmp_path: Path) -> None:
    """The exhibit's claim is that the foundation target is written before the refusal, so absence is a failure."""
    (tmp_path / "ig" / "input" / "fsh").mkdir(parents=True)

    outcome = check_refusal_leftovers(tmp_path)

    assert outcome.status == "FAIL"
    assert "aliases.fsh, foundation" in outcome.detail


def test_the_exhibit_fails_where_a_compile_is_on_disk(tmp_path: Path) -> None:
    """Nothing the refused run left compiles, so a compile beside it means the exhibit stopped being one."""
    project = _refused_project(tmp_path)
    (project / "ig" / "fsh-generated").mkdir(parents=True)

    outcome = check_refusal_leftovers(project)

    assert outcome.status == "FAIL"
    assert "fsh-generated" in outcome.detail


def test_every_refusing_guide_is_in_the_catalog() -> None:
    """The exhibit named here is a directory of the catalog, so the inversion is never keyed to a typo."""
    catalog = {project.name for project in discover_projects()}

    assert catalog, f"expected at least one guide under {IGS_ROOT}"
    assert catalog >= REFUSING_PROJECTS


def test_the_catalog_commits_no_generated_tree() -> None:
    """What a guide commits is its input: `d2w fhir generate` writes the rest, and `make verify-igs` runs it.

    Read off the index rather than the working tree, because a checkout that has run the catalog
    holds every generated file on disk - ignored, regenerable, and no part of what a reader browses.
    The hand-authored halves are the two the scaffold writes: `aliases.fsh` and `index.md`.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the committed file set cannot be read")
    committed = subprocess.run(  # noqa: S603 - every argument is a literal
        ["git", "-C", str(IGS_ROOT), "ls-files", "--", "."],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    generated = [
        path
        for path in committed
        if ("/ig/input/fsh/" in path and not path.endswith("/aliases.fsh"))
        or ("/ig/input/pagecontent/" in path and not path.endswith("/index.md"))
    ]

    assert committed, f"expected a committed catalog under {IGS_ROOT}"
    assert not generated, f"the catalog commits generated files: {generated}"
