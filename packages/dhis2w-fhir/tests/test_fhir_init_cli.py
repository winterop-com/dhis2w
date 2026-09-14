"""CliRunner tests for `d2w fhir init`."""

from __future__ import annotations

from pathlib import Path

import pytest
from dhis2w_cli.main import build_app
from typer.testing import CliRunner

_runner = CliRunner()


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run in an empty temporary working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_scaffolds_project(workdir: Path) -> None:
    """`d2w fhir init DIR` writes the full scaffold."""
    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--id", "dhis2.fhir.test"])
    assert result.exit_code == 0, result.output
    project = workdir / "project"
    for relative_path in ["fhir.toml", "ig/sushi-config.yaml", "ig/ig.ini", "ig/input/fsh/aliases.fsh", "Makefile"]:
        assert (project / relative_path).exists(), relative_path
    assert "id: dhis2.fhir.test" in (project / "ig" / "sushi-config.yaml").read_text(encoding="utf-8")


def test_init_skips_existing_without_force(workdir: Path) -> None:
    """A second init leaves existing files alone and reports them as skipped."""
    assert _runner.invoke(build_app(), ["fhir", "init", "project"]).exit_code == 0
    marker = workdir / "project" / "fhir.toml"
    marker.write_text("# customized\n", encoding="utf-8")
    result = _runner.invoke(build_app(), ["fhir", "init", "project"])
    assert result.exit_code == 0, result.output
    assert marker.read_text(encoding="utf-8") == "# customized\n"
    assert "skipped" in result.output


def test_init_force_overwrites(workdir: Path) -> None:
    """`--force` rewrites scaffold files that already exist."""
    assert _runner.invoke(build_app(), ["fhir", "init", "project"]).exit_code == 0
    marker = workdir / "project" / "fhir.toml"
    marker.write_text("# customized\n", encoding="utf-8")
    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--force"])
    assert result.exit_code == 0, result.output
    assert "[ig]" in marker.read_text(encoding="utf-8")


def test_init_seeds_data_definition_targets(workdir: Path) -> None:
    """Repeatable `--data-set` / `--event-program` / `--tracker-program` seed the include lists, offline."""
    import tomllib

    result = _runner.invoke(
        build_app(),
        [
            "fhir",
            "init",
            "project",
            "--data-set",
            "BfMAe6Itzgt",
            "--data-set",
            "Nyh6laLdBEJ",
            "--event-program",
            "VBqh0ynB2wv",
            "--tracker-program",
            "IpHINAT79UW",
            "--tracker-program",
            "uy2gU8kT1jF",
        ],
    )
    assert result.exit_code == 0, result.output
    raw = tomllib.loads((workdir / "project" / "fhir.toml").read_text(encoding="utf-8"))
    assert raw["generate"]["data_sets"]["include_ids"] == ["BfMAe6Itzgt", "Nyh6laLdBEJ"]
    assert raw["generate"]["event_programs"]["include_ids"] == ["VBqh0ynB2wv"]
    assert raw["generate"]["tracker_programs"]["include_ids"] == ["IpHINAT79UW", "uy2gU8kT1jF"]


def test_init_refresh_of_a_seeded_project_leaves_fhir_toml_alone(workdir: Path) -> None:
    """A refresh of a project seeded with tracker programs rewrites no configuration and reports no edits."""
    seeded = ["fhir", "init", "project", "--tracker-program", "IpHINAT79UW"]
    assert _runner.invoke(build_app(), seeded).exit_code == 0
    config = workdir / "project" / "fhir.toml"
    before = config.read_text(encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert config.read_text(encoding="utf-8") == before
    assert "[generate.tracker_programs]" in before
    assert "your version stays" not in result.output
    assert "unchanged ig/sushi-config.yaml" in result.output


def test_init_seeds_profile(workdir: Path) -> None:
    """`--profile` writes the `profile` key so generate reads that instance without a flag."""
    import tomllib

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--profile", "sldemo"])
    assert result.exit_code == 0, result.output
    raw = tomllib.loads((workdir / "project" / "fhir.toml").read_text(encoding="utf-8"))
    assert raw["profile"] == "sldemo"
    assert "next: run `d2w fhir generate` (profile `sldemo`)" in result.output


def test_init_without_profile_leaves_key_commented(workdir: Path) -> None:
    """Without `--profile` the key stays commented out, so fhir.toml parses with no profile set."""
    import tomllib

    result = _runner.invoke(build_app(), ["fhir", "init", "project"])
    assert result.exit_code == 0, result.output
    text = (workdir / "project" / "fhir.toml").read_text(encoding="utf-8")
    assert '# profile = "myserver"' in text
    assert "profile" not in tomllib.loads(text)


def test_init_profile_is_offline(workdir: Path) -> None:
    """An unknown profile name is written as given - init never resolves it against profiles.toml."""
    import tomllib

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--profile", "no-such-profile"])
    assert result.exit_code == 0, result.output
    raw = tomllib.loads((workdir / "project" / "fhir.toml").read_text(encoding="utf-8"))
    assert raw["profile"] == "no-such-profile"


def test_init_max_level_seeds_registry_cap(workdir: Path) -> None:
    """`--max-level` lands in fhir.toml; a level below 1 is a usage error, not a silently empty registry."""
    import tomllib

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--max-level", "4"])
    assert result.exit_code == 0, result.output
    raw = tomllib.loads((workdir / "project" / "fhir.toml").read_text(encoding="utf-8"))
    assert raw["generate"]["organisation_units"]["max_level"] == 4

    rejected = _runner.invoke(build_app(), ["fhir", "init", "other", "--max-level", "0"])
    assert rejected.exit_code != 0


def test_init_status_flag(workdir: Path) -> None:
    """`--status active` lands in fhir.toml and sushi-config; anything else is a usage error."""
    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--status", "active"])
    assert result.exit_code == 0, result.output
    assert 'status = "active"' in (workdir / "project" / "fhir.toml").read_text(encoding="utf-8")
    assert "status: active" in (workdir / "project" / "ig" / "sushi-config.yaml").read_text(encoding="utf-8")
    rejected = _runner.invoke(build_app(), ["fhir", "init", "other", "--status", "retired"])
    assert rejected.exit_code != 0


def test_init_json_output(workdir: Path) -> None:  # noqa: ARG001
    """`--json` emits the ScaffoldReport as JSON."""
    result = _runner.invoke(build_app(), ["--json", "fhir", "init", "project"])
    assert result.exit_code == 0, result.output
    assert '"created_files"' in result.output


def _scaffold(workdir: Path) -> Path:
    """Scaffold a project to refresh and return its directory."""
    assert _runner.invoke(build_app(), ["fhir", "init", "project", "--id", "dhis2.fhir.test"]).exit_code == 0
    return workdir / "project"


def test_init_refresh_rewrites_an_untouched_support_file(workdir: Path) -> None:
    """A support file the user never touched is brought up to the current scaffold."""
    project = _scaffold(workdir)
    ignored = project / ".gitignore"
    ignored.write_text("reports/\nig/output/\n", encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert "refreshed .gitignore" in result.output
    assert "ig/input/resources/" in ignored.read_text(encoding="utf-8").splitlines()


def test_init_refresh_rewrites_the_makefile_the_scaffold_owns(workdir: Path) -> None:
    """The Makefile is the scaffold's file, so a replaced recipe line is rewritten from the current render."""
    project = _scaffold(workdir)
    makefile = project / "Makefile"
    rendered = makefile.read_text(encoding="utf-8")
    makefile.write_text(rendered.replace("IG_DIR := ig", "IG_DIR := ig\nSTALE := 1", 1), encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert "rewritten Makefile (scaffold-owned; an edit to it does not survive a refresh)" in result.output
    assert makefile.read_text(encoding="utf-8") == rendered


def test_init_refresh_names_the_file_the_scaffold_no_longer_writes(workdir: Path) -> None:
    """A project carrying fhir.toml.example gains fhir.example.toml and is told it can delete the old file."""
    project = _scaffold(workdir)
    (project / "fhir.example.toml").rename(project / "fhir.toml.example")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert "created fhir.example.toml" in result.output
    assert "fhir.toml.example is not a scaffold file; delete it, fhir.example.toml has replaced it" in result.stderr
    assert (project / "fhir.toml.example").is_file()


def test_init_refresh_keeps_a_rewritten_file_and_claims_no_author(workdir: Path) -> None:
    """A rewritten file stays byte-identical, and the verdict states the fact rather than who caused it."""
    project = _scaffold(workdir)
    suppressed = project / "ig" / "input" / "ignoreWarnings.txt"
    edited = "== Ours ==\n\nOur own suppression.\n"
    suppressed.write_text(edited, encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert suppressed.read_text(encoding="utf-8") == edited
    assert "kept ig/input/ignoreWarnings.txt (holds lines the current scaffold does not write)" in result.output
    assert "you edited" not in result.output
    assert "your edits, or scaffold lines that have since changed" in result.output


def test_init_refresh_gives_a_stale_sushi_config_its_path_resource_block(workdir: Path) -> None:
    """A project scaffolded before path-resource existed publishes an IG missing registry and terminology."""
    project = _scaffold(workdir)
    sushi_config = project / "ig" / "sushi-config.yaml"
    dropped = {
        "  path-resource:",
        "    - input/resources/registry/*",
        "    - input/resources/terminology/*",
        "    - input/resources/concept-maps/*",
    }
    stale = [line for line in sushi_config.read_text(encoding="utf-8").splitlines() if line not in dropped]
    sushi_config.write_text("\n".join(stale) + "\n", encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert "refreshed ig/sushi-config.yaml" in result.output
    restored = sushi_config.read_text(encoding="utf-8")
    assert "  path-resource:" in restored
    assert "    - input/resources/concept-maps/*" in restored


def test_init_refresh_keeps_a_hand_tuned_sushi_config(workdir: Path) -> None:
    """The same file, hand-tuned on one line, keeps the user's version - a refresh never merges."""
    project = _scaffold(workdir)
    sushi_config = project / "ig" / "sushi-config.yaml"
    edited = sushi_config.read_text(encoding="utf-8").replace("version: 0.1.0", "version: 2.0.0")
    sushi_config.write_text(edited, encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert sushi_config.read_text(encoding="utf-8") == edited
    assert "kept ig/sushi-config.yaml (holds lines the current scaffold does not write)" in result.output


def test_init_refresh_names_a_pure_addition_as_yours_and_current(workdir: Path) -> None:
    """A file carrying the whole current scaffold plus a line of the user's own is not diverged."""
    project = _scaffold(workdir)
    gitignore = project / ".gitignore"
    gitignore.write_text(gitignore.read_text(encoding="utf-8") + "my-own-entry/\n", encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert "kept .gitignore (already carries the current scaffold, plus lines of your own)" in result.output
    assert "your edits, or scaffold lines that have since changed" not in result.output


def test_init_refresh_never_writes_fhir_toml(workdir: Path) -> None:
    """fhir.toml holds the IG identity, the profile, and the generation tables - all the user's."""
    project = _scaffold(workdir)
    config_path = project / "fhir.toml"
    body = config_path.read_text(encoding="utf-8") + "\n[serve]\nport = 8390\n"
    config_path.write_text(body, encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert config_path.read_text(encoding="utf-8") == body
    assert "fhir.toml is yours" in result.output


def test_init_refresh_rejects_force(workdir: Path) -> None:
    """--force overwrites what you edited and --refresh protects it; asking for both is a usage error."""
    project = _scaffold(workdir)
    marker = project / "Makefile"
    marker.write_text("# customized\n", encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh", "--force"])

    assert result.exit_code != 0
    assert marker.read_text(encoding="utf-8") == "# customized\n"


def test_init_refresh_requires_an_existing_project(workdir: Path) -> None:
    """Refreshing a directory with no fhir.toml points at the command that scaffolds one."""
    (workdir / "empty").mkdir()

    result = _runner.invoke(build_app(), ["fhir", "init", "empty", "--refresh"])

    assert result.exit_code == 1
    assert isinstance(result.exception, LookupError)
    assert "d2w fhir init" in str(result.exception)
    assert not (workdir / "empty" / "Makefile").exists()


def test_init_refresh_json_output(workdir: Path) -> None:
    """`--json` emits the refresh report, so a script can read what each file did."""
    _scaffold(workdir)

    result = _runner.invoke(build_app(), ["--json", "fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert '"rewritten_files"' in result.output
    assert '"refreshed_files"' in result.output
    assert '"unchanged_files"' in result.output
    assert '"extended_files"' in result.output
    assert '"diverged_files"' in result.output


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--id", "dhis2.fhir.other"),
        ("--canonical", "http://other.example/fhir"),
        ("--name", "OtherIg"),
        ("--title", "Other IG"),
        ("--publisher", "Other Organisation"),
        ("--status", "active"),
        ("--publisher-url", "http://other.example"),
        ("--profile", "sldemo"),
        ("--sushi-timeout", "5400"),
        ("--max-level", "3"),
        ("--data-set", "BfMAe6Itzgt"),
        ("--event-program", "VBqh0ynB2wv"),
        ("--tracker-program", "IpHINAT79UW"),
    ],
)
def test_init_refresh_rejects_a_scaffold_content_flag(workdir: Path, flag: str, value: str) -> None:
    """A refresh reads identity off fhir.toml, so a flag that seeds it is refused by name."""
    _scaffold(workdir)

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh", flag, value])

    assert result.exit_code != 0
    assert flag in result.output


def test_init_refresh_names_every_flag_it_refuses(workdir: Path) -> None:
    """Two ignored flags are both named, so a caller fixes the invocation in one pass."""
    _scaffold(workdir)

    result = _runner.invoke(
        build_app(), ["fhir", "init", "project", "--refresh", "--publisher", "Other", "--max-level", "3"]
    )

    assert result.exit_code != 0
    assert "--publisher" in result.output
    assert "--max-level" in result.output


def test_init_refresh_labels_the_files_it_kept(workdir: Path) -> None:
    """The summary row for a diverged file says the file was kept, not that the refresh skipped work."""
    project = _scaffold(workdir)
    suppressed = project / "ig" / "input" / "ignoreWarnings.txt"
    suppressed.write_text("== Ours ==\n", encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert "diverged (kept)" in result.stderr
    assert "kept ig/input/ignoreWarnings.txt (holds lines the current scaffold does not write)" in result.stderr


def test_init_renders_its_narration_on_stderr(workdir: Path) -> None:  # noqa: ARG001
    """The scaffold table, the file lines, and the next-step hint are narration, so stdout stays free."""
    result = _runner.invoke(build_app(), ["fhir", "init", "project"])

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "fhir init" in result.stderr
    assert "next: set `profile` in fhir.toml, then run `d2w fhir generate`" in result.stderr


# --- what init refuses to write into a project -----------------------------------------------------


@pytest.mark.parametrize("flag", ["--title", "--name"])
@pytest.mark.parametrize("character", ["<", ">"])
def test_init_refuses_an_identity_carrying_a_bracket(workdir: Path, flag: str, character: str) -> None:
    """The IG publisher strict-parses the pages it writes these into, so the run stops before a file lands."""
    value = f"Demo {character}Guide{character}" if flag == "--title" else f"Demo{character}Guide"

    result = _runner.invoke(build_app(), ["fhir", "init", "project", flag, value])

    assert result.exit_code != 0
    message = " ".join(result.output.replace("│", " ").split())
    assert flag in message
    assert f"carries '{character}'" in message
    assert not (workdir / "project").exists()


@pytest.mark.parametrize(
    "given",
    ["sierra leone", "Sierra Leone HMIS", "4Guide", "Guide-One", "Sierra Leone Health & Aid Demo Guide"],
)
def test_init_refuses_a_name_outside_the_fhir_shape(workdir: Path, given: str) -> None:
    """SUSHI rewrites a name it cannot use without saying so, so the shape is stated and refused here."""
    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--name", given])

    assert result.exit_code != 0
    assert "--name" in result.output
    assert not (workdir / "project").exists()


def test_init_derives_a_name_the_fhir_shape_accepts(workdir: Path) -> None:
    """The name `--id` yields on its own is one FHIR accepts, whatever the id is spelled like."""
    from dhis2w_fhir.names import FHIR_NAME_MAX_LENGTH, is_fhir_name

    long_id = "dhis2.fhir." + "segment." * 60

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--id", long_id])

    assert result.exit_code == 0, result.output
    published = (workdir / "project" / "ig" / "sushi-config.yaml").read_text(encoding="utf-8")
    derived = next(line.removeprefix("name: ") for line in published.splitlines() if line.startswith("name: "))
    assert is_fhir_name(derived)
    assert len(derived) <= FHIR_NAME_MAX_LENGTH


@pytest.mark.parametrize("flag", ["--data-set", "--event-program", "--tracker-program"])
def test_init_refuses_a_selection_uid_outside_the_dhis2_shape(workdir: Path, flag: str) -> None:
    """A UID is checked for shape offline, so a typo is caught here rather than as a guide of no forms."""
    result = _runner.invoke(build_app(), ["fhir", "init", "project", flag, "not-a-uid!!"])

    assert result.exit_code != 0
    message = " ".join(result.output.replace("│", " ").split())
    assert flag in message
    assert "eleven characters" in message
    assert not (workdir / "project").exists()


def test_init_refuses_a_registry_path_no_directory_stands_at(workdir: Path) -> None:
    """The path is read from the project's own root, so the refusal names where it looked."""
    result = _runner.invoke(
        build_app(),
        [
            "fhir",
            "init",
            "project",
            "--registry-id",
            "dhis2.fhir.test.registry",
            "--registry-canonical",
            "http://example.org/fhir/registry",
            "--registry-path",
            "../does-not-exist",
        ],
    )

    assert result.exit_code != 0
    message = " ".join(result.output.replace("│", " ").split())
    assert "--registry-path ../does-not-exist" in message
    assert not (workdir / "project").exists()


def test_init_accepts_a_registry_path_a_directory_stands_at(workdir: Path) -> None:
    """A checkout beside the project is what the flag is for, so the run scaffolds."""
    (workdir / "registry").mkdir()

    result = _runner.invoke(
        build_app(),
        [
            "fhir",
            "init",
            "project",
            "--registry-id",
            "dhis2.fhir.test.registry",
            "--registry-canonical",
            "http://example.org/fhir/registry",
            "--registry-path",
            "../registry",
        ],
    )

    assert result.exit_code == 0, result.output
    assert 'path = "../registry"' in (workdir / "project" / "fhir.toml").read_text(encoding="utf-8")


def test_init_force_reports_every_file_it_overwrote(workdir: Path) -> None:
    """`--force` discards a configured project, so the report says overwritten and names what it replaced."""
    assert _runner.invoke(build_app(), ["fhir", "init", "project"]).exit_code == 0
    config = workdir / "project" / "fhir.toml"
    config.write_text(config.read_text(encoding="utf-8") + "\n[serve]\nport = 8391\n", encoding="utf-8")

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--force"])

    assert result.exit_code == 0, result.output
    assert "overwritten fhir.toml" in result.stderr
    assert "created fhir.toml" not in result.stderr
    assert "--force replaced 13 file(s)" in result.stderr
    assert "port = 8391" not in config.read_text(encoding="utf-8")


def test_init_without_force_reports_nothing_overwritten(workdir: Path) -> None:  # noqa: ARG001
    """A first scaffold creates; only a run over a file that already stood there overwrites."""
    result = _runner.invoke(build_app(), ["--json", "fhir", "init", "project"])

    assert result.exit_code == 0, result.output
    assert '"overwritten_files": []' in result.output


def test_init_refresh_says_which_files_it_rewrites_whole(workdir: Path) -> None:
    """Five toolchain files are the scaffold's own, so the report gives them a verdict of their own."""
    project = _scaffold(workdir)
    makefile = project / "Makefile"
    makefile.write_text(
        makefile.read_text(encoding="utf-8").replace(
            "TX_SERVER ?= http://tx.fhir.org", "TX_SERVER ?= http://my-own-tx.example.org", 1
        ),
        encoding="utf-8",
    )

    result = _runner.invoke(build_app(), ["fhir", "init", "project", "--refresh"])

    assert result.exit_code == 0, result.output
    assert "rewritten (scaffold-owned)" in result.stderr
    assert "rewritten Makefile (scaffold-owned; an edit to it does not survive a refresh)" in result.stderr
    assert "refreshed Makefile" not in result.stderr
    assert "TX_SERVER ?= http://tx.fhir.org" in makefile.read_text(encoding="utf-8")


def test_the_scaffolded_makefile_says_an_edit_to_it_does_not_survive_a_refresh(workdir: Path) -> None:
    """The file a refresh rewrites whole is the one place a reader looks before editing it."""
    project = _scaffold(workdir)

    header = (project / "Makefile").read_text(encoding="utf-8").splitlines()[:4]

    assert "An edit written into THIS file does not survive that." in " ".join(header)


def test_init_help_names_the_files_a_refresh_rewrites_whole(workdir: Path) -> None:  # noqa: ARG001
    """The promise that edits survive holds for every file the help does not name here."""
    result = _runner.invoke(build_app(), ["fhir", "init", "--help"])

    assert result.exit_code == 0, result.output
    help_text = " ".join(result.output.replace("│", " ").split())
    for named in ("Makefile", "Dockerfile", ".python-version", "ig/ig.ini", "ig/fsh.ini"):
        assert named in help_text, named
    assert "does not survive" in help_text


@pytest.mark.parametrize("flag", ["--data-set", "--event-program", "--tracker-program"])
def test_init_help_says_naming_one_family_leaves_the_others_at_all(workdir: Path, flag: str) -> None:  # noqa: ARG001
    """An absent selection table means every member of its kind, which is the surprise the help removes."""
    result = _runner.invoke(build_app(), ["fhir", "init", "--help"])

    assert result.exit_code == 0, result.output
    help_text = " ".join(result.output.replace("│", " ").split())
    assert flag in help_text
    assert "Naming one family narrows that family alone" in help_text
