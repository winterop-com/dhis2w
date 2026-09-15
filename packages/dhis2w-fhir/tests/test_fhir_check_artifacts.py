"""Tests for `d2w fhir check-artifacts` - the generate-time build refusal read off the disk.

The point of the command is that it refuses what `d2w fhir generate` refuses, on files generate never
saw. So the assertions are about parity and about naming: the same predicates, the same character, and
a finding that carries the file and the element rather than a count.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from dhis2w_cli.main import build_app
from dhis2w_fhir import validation
from dhis2w_fhir.config import load_project
from dhis2w_fhir.resources.attribute_combos.restrictions import ATTRIBUTE_OPTION_RESTRICTION_PROPERTY
from dhis2w_fhir.validation import artifacts
from dhis2w_fhir.validation.artifacts import check_publishable_artifacts
from dhis2w_fhir.writer import GENERATED_HEADER
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

_runner = CliRunner()

_MINIMAL_TOML = """
[ig]
id = "dhis2.fhir.check"
canonical = "http://example.org/fhir/check"
name = "CheckExample"
title = "Check example guide"
publisher = "Example Organisation"
"""

#: The one character the IG publisher cannot survive, in the positions each test plants it in.
_ABORTING_NAME = "Mortality <5 years"
_ABORTING_CODE = "AGE<5"


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """An empty scaffolded-shaped project: a fhir.toml and the three trees a build publishes from."""
    (tmp_path / "fhir.toml").write_text(_MINIMAL_TOML, encoding="utf-8")
    for relative in ("ig/fsh-generated/resources", "ig/input/resources/terminology", "ig/input/fsh/foundation"):
        (tmp_path / relative).mkdir(parents=True)
    return tmp_path


def _write_resource(path: Path, document: dict[str, Any]) -> None:
    """Write one compiled FHIR resource where a publisher run would read it."""
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def _write_generated_fsh(path: Path, body: str) -> None:
    """Write one FSH source carrying the header that marks it as this toolchain's output."""
    path.write_text(f"{GENERATED_HEADER}\n\n{body}", encoding="utf-8")


def _report(root: Path) -> artifacts.ArtifactCheckReport:
    """Scan the project rooted at `root` the way the command does."""
    return check_publishable_artifacts(load_project(root))


def test_the_predicates_are_the_generate_gates_own(project_root: Path) -> None:
    """The scan calls the emit-site predicates themselves, so the two gates can never drift apart.

    Identity rather than behaviour: a copy that happens to agree today is exactly the drift the
    single source of truth exists to prevent. Read out of the module's own namespace, because the
    predicates are what the scan imports rather than part of what it exports.
    """
    scan_namespace = vars(artifacts)
    assert scan_namespace["build_aborting_name"] is validation.build_aborting_name
    assert scan_namespace["build_aborting_code"] is validation.build_aborting_code


def test_a_clean_tree_is_a_build_that_may_start(project_root: Path) -> None:
    """A project whose artifacts carry nothing hostile reports no finding and every file as read."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-clean.json",
        {
            "resourceType": "CodeSystem",
            "id": "clean",
            "title": "Mortality under 5 years",
            "identifier": [{"value": "AGE_U5"}],
            "concept": [{"code": "u5", "display": "Under 5 years"}],
        },
    )
    _write_generated_fsh(
        project_root / "ig/input/fsh/foundation/clean.fsh",
        'Instance: clean-form\nInstanceOf: Questionnaire\nTitle: "Under 5 register"\n* item[0].text = "Deaths"\n',
    )
    report = _report(project_root)
    assert report.finding_count == 0
    assert report.json_file_count == 1
    assert report.fsh_file_count == 1
    assert report.unreadable_files == []


def test_a_hostile_name_in_a_generated_json_is_caught_with_its_file_and_field(project_root: Path) -> None:
    """A '<' in a compiled resource's title is named by file, resource, element, and value."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-d2-os-Age.json",
        {"resourceType": "CodeSystem", "id": "d2-os-Age", "title": _ABORTING_NAME},
    )
    finding = _report(project_root).findings[0]
    assert finding.file == "ig/fsh-generated/resources/CodeSystem-d2-os-Age.json"
    assert finding.resource_id == "d2-os-Age"
    assert finding.field == "title"
    assert finding.value == _ABORTING_NAME
    assert finding.kind == "name"
    assert "d2w fhir generate" in finding.remedy


def test_a_hostile_code_in_a_generated_json_is_caught_as_an_identifier_value(project_root: Path) -> None:
    """A '<' in an emitted identifier value is named at the element it sits on, and graded as a code."""
    _write_resource(
        project_root / "ig/input/resources/terminology/ValueSet-ages.json",
        {"resourceType": "ValueSet", "id": "ages", "identifier": [{"system": "urn:d2"}, {"value": _ABORTING_CODE}]},
    )
    finding = _report(project_root).findings[0]
    assert finding.file == "ig/input/resources/terminology/ValueSet-ages.json"
    assert finding.resource_id == "ages"
    assert finding.field == "identifier[1].value"
    assert finding.value == _ABORTING_CODE
    assert finding.kind == "code"


def test_a_value_outside_an_identifier_is_not_a_code_finding(project_root: Path) -> None:
    """Only an identifier value reaches the raw table cell, so a filter value carrying '<' is left alone."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/ValueSet-filtered.json",
        {
            "resourceType": "ValueSet",
            "id": "filtered",
            "compose": {"include": [{"filter": [{"property": "age", "op": "=", "value": _ABORTING_CODE}]}]},
        },
    )
    assert _report(project_root).finding_count == 0


def test_every_display_and_question_label_is_read(project_root: Path) -> None:
    """The concept displays and question labels the emit-site member and question gates cover are covered here."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-options.json",
        {"resourceType": "CodeSystem", "id": "options", "concept": [{"code": "a"}, {"code": "b", "display": "<1y"}]},
    )
    _write_resource(
        project_root / "ig/fsh-generated/resources/Questionnaire-form.json",
        {"resourceType": "Questionnaire", "id": "form", "item": [{"linkId": "q1", "text": _ABORTING_NAME}]},
    )
    fields = {(finding.file.rsplit("/", 1)[-1], finding.field) for finding in _report(project_root).findings}
    assert fields == {("CodeSystem-options.json", "concept[1].display"), ("Questionnaire-form.json", "item[0].text")}


def test_a_narrative_is_not_read_as_a_name(project_root: Path) -> None:
    """A resource's `text` is a Narrative whose `div` is HTML by contract, so its tags are not findings."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-narrated.json",
        {
            "resourceType": "CodeSystem",
            "id": "narrated",
            "text": {"status": "generated", "div": "<div xmlns='http://www.w3.org/1999/xhtml'>ok</div>"},
        },
    )
    assert _report(project_root).finding_count == 0


def test_a_hand_authored_fsh_source_with_a_hostile_name_is_caught(project_root: Path) -> None:
    """A FSH file no gate has ever seen is scanned too, and its remedy says the file rather than DHIS2."""
    (project_root / "ig/input/fsh/local").mkdir()
    (project_root / "ig/input/fsh/local/mortality.fsh").write_text(
        "Instance: mortality-register\n"
        "InstanceOf: Questionnaire\n"
        f'Title: "{_ABORTING_NAME}"\n'
        '* item[0].text = "Deaths <5 this month"\n',
        encoding="utf-8",
    )
    report = _report(project_root)
    assert [finding.field for finding in report.findings] == ["Title:", "item[0].text"]
    assert {finding.resource_id for finding in report.findings} == {"mortality-register"}
    assert all("hand-authored" in finding.remedy for finding in report.findings)


def test_a_generated_fsh_source_is_answered_by_regenerating(project_root: Path) -> None:
    """The same '<' in a file this toolchain wrote asks for a rename in DHIS2, not an edit of the file."""
    _write_generated_fsh(
        project_root / "ig/input/fsh/foundation/ages.fsh",
        f'CodeSystem: D2Ages\n* #u5 "{_ABORTING_NAME}"\n',
    )
    finding = _report(project_root).findings[0]
    assert finding.field == "#u5 display"
    assert finding.resource_id == "D2Ages"
    assert "narrow the selection" in finding.remedy


def test_a_fsh_identifier_value_is_read_as_a_code(project_root: Path) -> None:
    """A FSH assignment to an identifier value is the code half of the gate, on the FSH side."""
    _write_generated_fsh(
        project_root / "ig/input/fsh/foundation/org.fsh",
        f'Instance: d2-org-a\nInstanceOf: Organization\n* identifier[0].value = "{_ABORTING_CODE}"\n',
    )
    finding = _report(project_root).findings[0]
    assert finding.kind == "code"
    assert finding.field == "identifier[0].value"


def test_a_file_that_is_not_json_is_named_rather_than_passed_over(project_root: Path) -> None:
    """An unparseable file under a scanned tree is reported, so a clean verdict never hides an unread file."""
    (project_root / "ig/fsh-generated/resources/broken.json").write_text("{not json", encoding="utf-8")
    report = _report(project_root)
    assert report.unreadable_files == ["ig/fsh-generated/resources/broken.json"]
    assert report.finding_count == 0


def test_a_json_file_that_holds_no_resource_is_passed_over_in_silence(project_root: Path) -> None:
    """The SUSHI index beside the compiled resources is bookkeeping, not a page, so it is neither read nor flagged."""
    (project_root / "ig/fsh-generated/data").mkdir(parents=True)
    (project_root / "ig/fsh-generated/data/fsh-index.json").write_text(
        json.dumps([{"outputFile": "x.json", "fshName": _ABORTING_NAME}]), encoding="utf-8"
    )
    report = _report(project_root)
    assert report.finding_count == 0
    assert report.unreadable_files == []


def test_findings_read_in_one_stable_order(project_root: Path) -> None:
    """Two runs over one unchanged tree read identically: file, then resource, then element."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-b.json",
        {"resourceType": "CodeSystem", "id": "b", "title": _ABORTING_NAME},
    )
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-a.json",
        {"resourceType": "CodeSystem", "id": "a", "name": _ABORTING_NAME, "title": _ABORTING_NAME},
    )
    assert [(finding.resource_id, finding.field) for finding in _report(project_root).findings] == [
        ("a", "name"),
        ("a", "title"),
        ("b", "title"),
    ]


def test_the_command_exits_zero_on_a_clean_project(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean tree is a build that may start, and the command says so without a connection."""
    monkeypatch.chdir(project_root)
    result = _runner.invoke(build_app(), ["fhir", "check-artifacts"])
    assert result.exit_code == 0, result.output


def test_the_command_exits_one_and_names_the_object(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A finding refuses the build before the publisher runs, naming the file and the offending value."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-d2-os-Age.json",
        {"resourceType": "CodeSystem", "id": "d2-os-Age", "title": _ABORTING_NAME},
    )
    monkeypatch.chdir(project_root)
    result = _runner.invoke(build_app(), ["fhir", "check-artifacts"])
    assert result.exit_code == 1, result.output
    assert "d2-os-Age" in result.output
    assert "title" in result.output
    assert "1 build-aborting artifact(s) found" in result.output


def test_no_fail_reports_the_findings_and_exits_zero(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--no-fail` keeps the report and drops the gate, for a caller reading rather than gating."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-d2-os-Age.json",
        {"resourceType": "CodeSystem", "id": "d2-os-Age", "title": _ABORTING_NAME},
    )
    monkeypatch.chdir(project_root)
    result = _runner.invoke(build_app(), ["fhir", "check-artifacts", "--no-fail"])
    assert result.exit_code == 0, result.output


def test_the_json_payload_carries_every_finding(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--json` writes the typed report on stdout, remedy and all, and still exits 1."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-d2-os-Age.json",
        {"resourceType": "CodeSystem", "id": "d2-os-Age", "title": _ABORTING_NAME},
    )
    monkeypatch.chdir(project_root)
    result = _runner.invoke(build_app(), ["--json", "fhir", "check-artifacts"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["findings"][0]["value"] == _ABORTING_NAME
    assert payload["findings"][0]["field"] == "title"


def test_the_command_scans_a_project_named_on_the_command_line(project_root: Path, tmp_path: Path) -> None:
    """A directory argument scans that project, so one checkout can gate several guides."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-d2-os-Age.json",
        {"resourceType": "CodeSystem", "id": "d2-os-Age", "title": _ABORTING_NAME},
    )
    result = _runner.invoke(build_app(), ["fhir", "check-artifacts", str(project_root)])
    assert result.exit_code == 1, result.output


def _write_sushi_config(root: Path, **identity: str) -> None:
    """Write the identity lines of a sushi-config in the shape the scaffold writes them."""
    description = identity.get("description", "Check example guide, generated from DHIS2 metadata by d2w fhir.")
    lines = [
        "id: dhis2.fhir.check",
        "canonical: http://example.org/fhir/check",
        f"name: {identity.get('name', 'CheckExample')}",
        f"title: {identity.get('title', 'Check example guide')}",
        f"description: {description}",
        "status: draft",
        "publisher:",
        f"  name: {identity.get('publisher', 'Example Organisation')}",
    ]
    (root / "ig/sushi-config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_ig_title_is_scanned_before_anything_has_compiled(project_root: Path) -> None:
    """The guide's own title aborts the publisher too, and a project that has only generated carries it nowhere else."""
    (project_root / "fhir.toml").write_text(
        _MINIMAL_TOML.replace('title = "Check example guide"', 'title = "Demo <Guide>"'), encoding="utf-8"
    )
    finding = _report(project_root).findings[0]
    assert finding.file == "fhir.toml"
    assert finding.field == "ig.title"
    assert finding.value == "Demo <Guide>"
    assert finding.origin is artifacts.FindingOrigin.IG_IDENTITY
    assert finding.severity == "build-aborting"


def test_an_ig_identity_finding_names_the_key_that_states_it(project_root: Path) -> None:
    """The publisher name came from fhir.toml, so the remedy is that table and a refresh - not a rename in DHIS2."""
    (project_root / "fhir.toml").write_text(
        _MINIMAL_TOML.replace('publisher = "Example Organisation"', 'publisher = "Ministry <Health>"'),
        encoding="utf-8",
    )
    finding = _report(project_root).findings[0]
    assert finding.remedy == "Change `[ig] publisher` in fhir.toml, then run `d2w fhir init --refresh`."
    assert "DHIS2" not in finding.remedy


def test_a_dhis2_name_keeps_the_remedy_that_names_dhis2(project_root: Path) -> None:
    """A finding on a generated artifact is still answered where the name lives, which is the instance."""
    _write_resource(
        project_root / "ig/fsh-generated/resources/CodeSystem-d2-os-Age.json",
        {"resourceType": "CodeSystem", "id": "d2-os-Age", "title": _ABORTING_NAME},
    )
    finding = _report(project_root).findings[0]
    assert finding.origin is artifacts.FindingOrigin.DHIS2
    assert "Rename it in DHIS2" in finding.remedy


def test_the_ig_description_is_scanned_where_the_publisher_reads_it(project_root: Path) -> None:
    """fhir.toml spells no description, so the one sushi-config carries is read off that file."""
    _write_sushi_config(project_root, description="Demo <Guide>, generated from DHIS2 metadata by d2w fhir.")
    finding = _report(project_root).findings[0]
    assert finding.file == "ig/sushi-config.yaml"
    assert finding.field == "description"
    assert finding.remedy.startswith("Change the `[ig]` table in fhir.toml")


def test_one_identity_stated_in_both_files_is_one_finding(project_root: Path) -> None:
    """fhir.toml is the source, so a sushi-config carrying the same value is not a second row about it."""
    (project_root / "fhir.toml").write_text(
        _MINIMAL_TOML.replace('title = "Check example guide"', 'title = "Demo <Guide>"'), encoding="utf-8"
    )
    _write_sushi_config(project_root, title="Demo <Guide>")
    assert [(finding.file, finding.field) for finding in _report(project_root).findings] == [("fhir.toml", "ig.title")]


def test_a_sushi_config_edited_away_from_fhir_toml_is_read_as_the_publisher_finds_it(project_root: Path) -> None:
    """The publisher reads sushi-config, so a title only that file carries is found where it sits."""
    _write_sushi_config(project_root, title="Demo <Guide>")
    finding = next(item for item in _report(project_root).findings if item.field == "title")
    assert finding.file == "ig/sushi-config.yaml"
    assert finding.remedy == "Change `[ig] title` in fhir.toml, then run `d2w fhir init --refresh`."


def _write_assignment_list(root: Path, list_id: str, *, entries: list[str]) -> None:
    """Write one organisation-unit assignment List where the generate target writes it."""
    directory = root / "ig/input/resources/assignments"
    directory.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "resourceType": "List",
        "id": list_id,
        "status": "current",
        "mode": "snapshot",
        "title": "ANC 1st visit - assigned organisation units",
    }
    if entries:
        document["entry"] = [{"item": {"reference": f"Location/{uid}"}} for uid in entries]
    _write_resource(directory / f"List-{list_id}.json", document)


def _write_assigned_form(root: Path, stem: str, list_id: str) -> None:
    """Write one generated Questionnaire naming the assignment List that scopes it."""
    _write_generated_fsh(
        root / f"ig/input/fsh/foundation/{stem}.fsh",
        f"Instance: Q{stem}\nInstanceOf: Questionnaire\n"
        f"* extension[assignment].valueReference = Reference(List/{list_id})\n",
    )


def test_a_form_whose_assignment_names_no_unit_is_a_warning(project_root: Path) -> None:
    """A form nobody can submit publishes perfectly well, so the build runs and the scan says what it costs."""
    _write_assignment_list(project_root, "d2-ds-BfMAe6Itzgt-org-units", entries=[])
    _write_assigned_form(project_root, "anc", "d2-ds-BfMAe6Itzgt-org-units")
    report = _report(project_root)
    finding = report.findings[0]
    assert finding.kind == "assignment"
    assert finding.severity == "warning"
    assert finding.resource_id == "anc"
    assert finding.value == "List/d2-ds-BfMAe6Itzgt-org-units"
    assert "max_level" in finding.remedy
    assert report.build_aborting_count == 0
    assert report.warning_count == 1


def test_an_assignment_that_names_a_unit_raises_nothing(project_root: Path) -> None:
    """A narrowed assignment is the artifact working as designed; only an empty one is a form nobody may report."""
    _write_assignment_list(project_root, "d2-ds-BfMAe6Itzgt-org-units", entries=["ImspTQPwCqd"])
    _write_assigned_form(project_root, "anc", "d2-ds-BfMAe6Itzgt-org-units")
    assert _report(project_root).finding_count == 0


def test_every_form_on_one_empty_assignment_is_counted(project_root: Path) -> None:
    """A tracker program's stages share one List and each publishes a form, so the count is of forms."""
    _write_assignment_list(project_root, "d2-pr-IpHINAT79UW-org-units", entries=[])
    for stage in ("A03MvHHogjR", "ZzYYXq4fJie"):
        _write_assigned_form(project_root, stage, "d2-pr-IpHINAT79UW-org-units")
    report = _report(project_root)
    assert report.warning_count == 2
    assert {finding.resource_id for finding in report.findings} == {"A03MvHHogjR", "ZzYYXq4fJie"}


def test_a_warning_alone_lets_the_build_start(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`make build` runs this to refuse a publisher run; an unusable form is not a reason to refuse one."""
    _write_assignment_list(project_root, "d2-ds-BfMAe6Itzgt-org-units", entries=[])
    _write_assigned_form(project_root, "anc", "d2-ds-BfMAe6Itzgt-org-units")
    monkeypatch.chdir(project_root)
    # Rich reads COLUMNS when stderr is captured; a wide surface keeps the remedy on one line, so
    # the assertion below meets the cell rather than the wrap of a narrow tty.
    monkeypatch.setenv("COLUMNS", "300")
    result = _runner.invoke(build_app(), ["fhir", "check-artifacts"])
    assert result.exit_code == 0, result.output
    assert "warning" in result.output
    # The bracketed table name reaches the reader: Rich reads `[generate.organisation_units]` as a
    # style tag and prints nothing in its place unless the cell states its own brackets.
    assert "[generate.organisation_units] max_level" in result.output


def _write_combo_vocabulary(root: Path, *, restricted_to: list[str], other_restricted_to: list[str]) -> None:
    """Write one attribute-combo vocabulary with two concepts, each scoped by a restriction List of its own."""
    directory = root / "ig/input/resources/attribute-option-combos"
    directory.mkdir(parents=True, exist_ok=True)
    system = "http://example.org/fhir/CodeSystem/d2-aoc-idcDPkDtepR-cs"
    for list_id, entries in (
        ("d2-aoc-yMj2MnmNI8L-org-units", restricted_to),
        ("d2-aoc-M58XdOfhiJ7-org-units", other_restricted_to),
    ):
        document: dict[str, Any] = {"resourceType": "List", "id": list_id, "status": "current", "mode": "snapshot"}
        if entries:
            document["entry"] = [{"item": {"reference": f"Location/{uid}"}} for uid in entries]
        _write_resource(directory / f"List-{list_id}.json", document)
    _write_resource(
        directory / "CodeSystem-d2-aoc-idcDPkDtepR-cs.json",
        {
            "resourceType": "CodeSystem",
            "id": "d2-aoc-idcDPkDtepR-cs",
            "url": system,
            "name": "D2AOC_idcDPkDtepR_CS",
            "status": "draft",
            "content": "complete",
            "concept": [
                {
                    "code": "BqblOcSwGey",
                    "property": [
                        {
                            "code": ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
                            "valueString": "List/d2-aoc-yMj2MnmNI8L-org-units",
                        }
                    ],
                },
                {
                    "code": "oawMLLH7OjA",
                    "property": [
                        {
                            "code": ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
                            "valueString": "List/d2-aoc-M58XdOfhiJ7-org-units",
                        }
                    ],
                },
            ],
        },
    )
    _write_resource(
        directory / "ValueSet-d2-aoc-idcDPkDtepR-vs.json",
        {
            "resourceType": "ValueSet",
            "id": "d2-aoc-idcDPkDtepR-vs",
            "url": "http://example.org/fhir/ValueSet/d2-aoc-idcDPkDtepR-vs",
            "name": "D2AOC_idcDPkDtepR_VS",
            "status": "draft",
            "compose": {"include": [{"system": system}]},
        },
    )


def _write_form_on_a_combo(root: Path, stem: str) -> None:
    """Write one generated Questionnaire binding the attribute-combo vocabulary by its FSH name."""
    _write_generated_fsh(
        root / f"ig/input/fsh/foundation/{stem}.fsh",
        f"Instance: Q{stem}\nInstanceOf: Questionnaire\n"
        "* extension[D2AttributeOptionCombos].valueCanonical = Canonical(D2AOC_idcDPkDtepR_VS)\n",
    )


def test_a_form_whose_every_combo_is_restricted_away_is_a_warning(project_root: Path) -> None:
    """No organisation unit may file any concept of the vocabulary, so every capture for the form earns E8025."""
    _write_combo_vocabulary(project_root, restricted_to=[], other_restricted_to=[])
    _write_form_on_a_combo(project_root, "epi-stock")
    report = _report(project_root)
    finding = report.findings[0]
    assert finding.kind == "attribute-option-combo"
    assert finding.severity == "warning"
    assert finding.resource_id == "epi-stock"
    assert finding.value == "D2AOC_idcDPkDtepR_VS"
    assert "max_level" in finding.remedy
    assert report.build_aborting_count == 0
    assert report.warning_count == 1


def test_one_usable_concept_is_a_vocabulary_somebody_may_file_under(project_root: Path) -> None:
    """A combo restricted to organisation units the project does publish is the artifact working as designed."""
    _write_combo_vocabulary(project_root, restricted_to=["ImspTQPwCqd"], other_restricted_to=[])
    _write_form_on_a_combo(project_root, "epi-stock")
    assert _report(project_root).finding_count == 0


def test_a_concept_restricted_by_two_lists_needs_one_unit_on_both(project_root: Path) -> None:
    """A combo is met from one option per axis, so a unit admits it only where every List names it."""
    _write_combo_vocabulary(project_root, restricted_to=["ImspTQPwCqd"], other_restricted_to=["O6uvpzGd5pu"])
    _write_form_on_a_combo(project_root, "epi-stock")
    assert _report(project_root).finding_count == 0


#: A guide selecting two data sets by UID: one the published tree carries, one it carries nowhere.
_SELECTION_TOML = f"""{_MINIMAL_TOML}
[generate.data_sets]
include_ids = ["BfMAe6Itzgt", "aBcDeFgHiJk"]
"""


def _write_selected_form(root: Path, uid: str) -> None:
    """Write one generated Questionnaire carrying the DHIS2 UID it was generated from."""
    _write_generated_fsh(
        root / f"ig/input/fsh/foundation/{uid}.fsh",
        f'Instance: Questionnaire-{uid}\nInstanceOf: Questionnaire\n* id = "{uid}"\n',
    )


def test_a_selection_entry_the_tree_carries_nothing_for_is_a_warning(project_root: Path) -> None:
    """A UID that selected nothing costs the guide a form, and the tree on disk is enough to say so."""
    (project_root / "fhir.toml").write_text(_SELECTION_TOML, encoding="utf-8")
    _write_selected_form(project_root, "BfMAe6Itzgt")
    report = _report(project_root)
    assert report.warning_count == 1
    assert report.build_aborting_count == 0
    finding = report.findings[0]
    assert finding.kind == "selection"
    assert finding.severity == "warning"
    assert finding.file == "fhir.toml"
    assert finding.resource_id == "generate.data_sets"
    assert finding.field == "include_ids"
    assert finding.value == "aBcDeFgHiJk"
    assert "Maintenance app" in finding.remedy


def test_a_selection_every_entry_of_which_published_raises_nothing(project_root: Path) -> None:
    """The finding states an exception: a UID the tree carries is the selection working as written."""
    (project_root / "fhir.toml").write_text(
        f'{_MINIMAL_TOML}\n[generate.data_sets]\ninclude_ids = ["BfMAe6Itzgt"]\n', encoding="utf-8"
    )
    _write_selected_form(project_root, "BfMAe6Itzgt")
    assert _report(project_root).finding_count == 0


def test_a_project_that_has_never_generated_says_nothing_about_its_selection(project_root: Path) -> None:
    """An empty tree is an empty tree; only a generated one says what a selection did or did not find."""
    (project_root / "fhir.toml").write_text(_SELECTION_TOML, encoding="utf-8")
    (project_root / "ig/input/fsh/foundation").rmdir()
    assert _report(project_root).finding_count == 0


def test_a_table_switched_off_selects_nothing_and_is_not_graded(project_root: Path) -> None:
    """`enabled = false` publishes no form of that kind by design, so its ids are not a selection that failed."""
    (project_root / "fhir.toml").write_text(
        f'{_MINIMAL_TOML}\n[generate.data_sets]\nenabled = false\ninclude_ids = ["aBcDeFgHiJk"]\n', encoding="utf-8"
    )
    assert _report(project_root).finding_count == 0
