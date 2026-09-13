"""The optional organisation-unit registry package: a guide that depends on one, and the package itself.

A `fhir.toml` without `[generate.organisation_units.registry]` behaves as it always has - the
registry is published inline and every reference is relative - so most of these tests pair a
registry-mode assertion with the inline one it must not disturb. The full runs are mocked
(respx); no live stack.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from dhis2w_cli.main import build_app
from dhis2w_core.profile import resolve_profile
from dhis2w_fhir import InitOptions, load_project, service
from dhis2w_fhir.config import FhirProjectConfig, GenerateConfig
from dhis2w_fhir.conversion.values import location_id_of
from dhis2w_fhir.foundation import build_foundation_artifacts, build_registry_foundation_artifacts
from dhis2w_fhir.names import StemResolution, StemSubject
from dhis2w_fhir.notes import GenerateNoteCategory
from dhis2w_fhir.resources.examples import location_reference
from dhis2w_fhir.resources.organisation_units import plan_organisation_unit_stems
from dhis2w_fhir.resources.organisation_units.naming import location_profile_reference
from dhis2w_fhir.resources.organisation_units.schemas import (
    OrganisationUnitIn,
    OrganisationUnitSelection,
    RegistryDependency,
)
from dhis2w_fhir.resources.pages import PAGES_DIRECTORY, build_page_artifacts, build_registry_page_artifacts
from dhis2w_fhir.resources.pages.schemas import PagesIn
from dhis2w_fhir.scaffold import build_scaffold_files
from dhis2w_fhir.scaffold.refresh import read_project_scaffold_state, refresh_project
from dhis2w_fhir.service import RegistryProjectTargetError
from typer.testing import CliRunner

_HOST = "https://dhis2.example"
_CANONICAL = "http://example.org/fhir"
_REGISTRY = RegistryDependency(
    id="dhis2.fhir.test.registry", canonical="http://example.org/fhir/registry/", version="1.2.0"
)
_REGISTRY_CONFIG = GenerateConfig(organisation_units=OrganisationUnitSelection(registry=_REGISTRY))
_INLINE_CONFIG = GenerateConfig()

_ROOT = OrganisationUnitIn(uid="ImspTQPwCqd", name="Sierra Leone", level=1, path="/ImspTQPwCqd", code="SL")
_DISTRICT = OrganisationUnitIn(
    uid="O6uvpzGd5pu", name="Bo", level=2, path="/ImspTQPwCqd/O6uvpzGd5pu", parent_uid="ImspTQPwCqd"
)
_SUBJECTS = [StemSubject(uid=unit.uid, code=unit.code, label=unit.name) for unit in (_ROOT, _DISTRICT)]

_ORGANISATION_UNITS_PAYLOAD = {
    "organisationUnits": [
        {"id": "ImspTQPwCqd", "name": "Sierra Leone", "level": 1, "path": "/ImspTQPwCqd", "code": "SL"},
        {
            "id": "O6uvpzGd5pu",
            "name": "Bo",
            "level": 2,
            "path": "/ImspTQPwCqd/O6uvpzGd5pu",
            "parent": {"id": "ImspTQPwCqd"},
            "description": "The district of Bo.",
            "geometry": {"type": "Point", "coordinates": [-11.7383, 7.9647]},
        },
    ]
}
_DATA_SETS_PAYLOAD = {
    "dataSets": [
        {
            "id": "BfMAe6Itzgt",
            "name": "Child Health",
            "periodType": "Monthly",
            "organisationUnits": [{"id": "O6uvpzGd5pu"}],
            "dataSetElements": [
                {
                    "dataElement": {
                        "id": "s46m5MS0hxu",
                        "name": "BCG doses",
                        "valueType": "INTEGER",
                        "categoryCombo": {"id": "bjDvmb4bfuf", "name": "default"},
                    }
                }
            ],
        }
    ]
}

_runner = CliRunner()


# --- the resolution and the reference form -------------------------------------------------------


def test_the_registry_dependency_derives_its_reference_base_and_guide_url() -> None:
    """The canonical loses its trailing slash once; the reference base and the dependsOn uri hang off it."""
    assert _REGISTRY.canonical == "http://example.org/fhir/registry"
    assert _REGISTRY.reference_base == "http://example.org/fhir/registry/"
    assert (
        _REGISTRY.implementation_guide_url
        == "http://example.org/fhir/registry/ImplementationGuide/dhis2.fhir.test.registry"
    )


def test_stems_are_the_same_in_both_modes_and_only_the_reference_base_differs() -> None:
    """A unit's id follows the naming source alone; the registry moves where a reference points, not what it names."""
    inline = plan_organisation_unit_stems(_SUBJECTS, "id")
    depending = plan_organisation_unit_stems(_SUBJECTS, "id", registry=_REGISTRY)

    assert depending.stems == inline.stems
    assert inline.reference_base == ""
    assert inline.reference_for("Location", "O6uvpzGd5pu") == "Location/O6uvpzGd5pu"
    assert depending.reference_for("Location", "O6uvpzGd5pu") == "http://example.org/fhir/registry/Location/O6uvpzGd5pu"
    assert location_reference("O6uvpzGd5pu", depending) == "http://example.org/fhir/registry/Location/O6uvpzGd5pu"
    assert location_reference("O6uvpzGd5pu", inline) == "Location/O6uvpzGd5pu"
    assert location_reference("O6uvpzGd5pu", None) == "Location/O6uvpzGd5pu"


def test_a_unit_outside_the_resolution_keeps_its_uid_under_the_registry_base() -> None:
    """The fall-back id rides the same base, so a reference is never half absolute."""
    resolution = StemResolution(stems={}, reference_base="http://example.org/fhir/registry/")
    assert location_reference("Zz1Zz1Zz1Zz", resolution) == "http://example.org/fhir/registry/Location/Zz1Zz1Zz1Zz"


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("Location/O6uvpzGd5pu", "O6uvpzGd5pu"),
        ("http://example.org/fhir/registry/Location/O6uvpzGd5pu", "O6uvpzGd5pu"),
        ("Location/", None),
        ("", None),
        ("Organization/O6uvpzGd5pu", None),
        ("http://example.org/fhir/registry/Location/O6uvpzGd5pu/_history/1", None),
        ("/Location/O6uvpzGd5pu", None),
    ],
)
def test_the_translator_reads_a_location_id_off_both_reference_forms(reference: str, expected: str | None) -> None:
    """A response written against either guide names one Location, and the id is what follows the last `Location/`."""
    assert location_id_of(reference) == expected


# --- foundation ----------------------------------------------------------------------------------


def _foundation(config: GenerateConfig) -> dict[str, str]:
    return {
        artifact.relative_path: artifact.content
        for artifact in build_foundation_artifacts(config, _CANONICAL, ig_status="draft")
    }


def test_the_guide_types_every_unit_reference_with_the_registry_profile_by_canonical() -> None:
    """`D2OrganisationUnit` and `D2Responses` reference the registry package's Location profile by URL."""
    registry_profile = "http://example.org/fhir/registry/StructureDefinition/d2-location"
    assert location_profile_reference(_REGISTRY_CONFIG) == registry_profile
    assert location_profile_reference(_INLINE_CONFIG) == "D2Location"

    depending = _foundation(_REGISTRY_CONFIG)
    assert f"* value[x] only Reference({registry_profile})" in depending["foundation/d2-organisation-unit.fsh"]
    assert f"* subject only Reference({registry_profile})" in depending["foundation/d2-responses.fsh"]

    inline = _foundation(_INLINE_CONFIG)
    assert "* value[x] only Reference(D2Location)" in inline["foundation/d2-organisation-unit.fsh"]
    assert "* subject only Reference(D2Location)" in inline["foundation/d2-responses.fsh"]


def test_the_guide_leaves_the_level_extension_and_the_unit_naming_systems_to_the_registry() -> None:
    """What only a Location carries is the registry package's to define; the guide defines the rest as before."""
    depending = _foundation(_REGISTRY_CONFIG)
    inline = _foundation(_INLINE_CONFIG)

    assert "foundation/d2-organisation-unit-level.fsh" in inline
    assert "foundation/d2-organisation-unit-level.fsh" not in depending
    assert set(inline) - set(depending) == {"foundation/d2-organisation-unit-level.fsh"}
    assert "Instance: D2OrgUnitIdentifierSystem" in inline["foundation/d2-naming-systems.fsh"]
    assert "Instance: D2OrgUnitIdentifierSystem" not in depending["foundation/d2-naming-systems.fsh"]
    assert "Instance: D2OrgUnitCodeIdentifierSystem" not in depending["foundation/d2-naming-systems.fsh"]
    assert "Instance: D2OptionSetIdentifierSystem" in depending["foundation/d2-naming-systems.fsh"]
    # The aliases are SUSHI-local and stay whole either way.
    assert depending["foundation/d2-aliases.fsh"] == inline["foundation/d2-aliases.fsh"]


def test_the_registry_package_foundation_is_the_slice_its_instances_name() -> None:
    """Aliases, the organisation-unit NamingSystems, the attribute-value and level extensions - nothing else."""
    artifacts = {
        artifact.relative_path: artifact.content
        for artifact in build_registry_foundation_artifacts(_INLINE_CONFIG, _CANONICAL, ig_status="draft")
    }

    assert set(artifacts) == {
        "foundation/d2-aliases.fsh",
        "foundation/d2-naming-systems.fsh",
        "foundation/d2-attribute-value.fsh",
        "foundation/d2-organisation-unit-level.fsh",
    }
    naming_systems = artifacts["foundation/d2-naming-systems.fsh"]
    assert naming_systems.count("Instance: ") == 2
    assert "Instance: D2OrgUnitIdentifierSystem" in naming_systems
    assert "Instance: D2OrgUnitCodeIdentifierSystem" in naming_systems
    assert "Extension: D2OrganisationUnitLevel" in artifacts["foundation/d2-organisation-unit-level.fsh"]
    assert artifacts["foundation/d2-aliases.fsh"] == _foundation(_INLINE_CONFIG)["foundation/d2-aliases.fsh"]


# --- pages ---------------------------------------------------------------------------------------


def test_the_registry_page_of_a_depending_guide_names_the_package_and_the_capture_page_references_into_it() -> None:
    """The guide read stems alone, so its Registry page states the package and its worked reference is absolute."""
    stems = plan_organisation_unit_stems(_SUBJECTS, "id", registry=_REGISTRY)
    build = build_page_artifacts(PagesIn(), _REGISTRY_CONFIG, _CANONICAL, organisation_unit_stems=stems)
    pages = {
        artifact.relative_path.removeprefix(f"{PAGES_DIRECTORY}/"): artifact.content for artifact in build.artifacts
    }

    registry = pages["registry.md"]
    assert registry.startswith("# Registry\n")
    assert "`dhis2.fhir.test.registry` (version 1.2.0, canonical\n`http://example.org/fhir/registry`)" in registry
    assert "resolves 2 published unit(s)" in registry
    assert "| Organisation units |" not in registry
    capture = pages["capture.md"]
    assert '"subject": { "reference": "http://example.org/fhir/registry/Location/ImspTQPwCqd" }' in capture
    assert "That is the DHIS2 organisation unit `ImspTQPwCqd`." in capture
    assert "`http://example.org/fhir/registry/StructureDefinition/d2-location`" in capture
    assert "`http://example.org/fhir/registry/Location/<organisationUnitId>` - the Location the registry" in capture
    assert not [name for name in pages if name.startswith("Organization-")]


def test_the_registry_page_of_an_inline_guide_still_tabulates_the_hierarchy() -> None:
    """Nothing about the inline page moved: totals, root, levels, profile pointers, relative worked reference."""
    build = build_page_artifacts(PagesIn(organisation_units=[_ROOT, _DISTRICT]), _INLINE_CONFIG, _CANONICAL)
    pages = {
        artifact.relative_path.removeprefix(f"{PAGES_DIRECTORY}/"): artifact.content for artifact in build.artifacts
    }

    assert "| Organisation units | 2 |" in pages["registry.md"]
    assert "published by the package" not in pages["registry.md"]
    assert '"subject": { "reference": "Location/ImspTQPwCqd" }' in pages["capture.md"]
    assert "Written out, that is Sierra Leone (`ImspTQPwCqd`)." in pages["capture.md"]
    assert "`D2Location`" in pages["capture.md"]
    assert "`Location/<organisationUnitId>` - the Location this guide publishes for that unit." in pages["capture.md"]


def test_the_registry_package_pages_are_the_registry_page_and_the_unit_intros() -> None:
    """A registry package narrates its units alone: no form catalog, terminology, identifier or capture page."""
    described = _DISTRICT.model_copy(update={"description": "The district of Bo."})
    build = build_registry_page_artifacts(PagesIn(organisation_units=[_ROOT, described]), _INLINE_CONFIG)
    names = sorted(artifact.relative_path.removeprefix(f"{PAGES_DIRECTORY}/") for artifact in build.artifacts)

    assert names == ["Organization-O6uvpzGd5pu-intro.md", "registry.md"]
    registry = next(artifact.content for artifact in build.artifacts if artifact.relative_path.endswith("registry.md"))
    assert "| Organisation units | 2 |" in registry


# --- config --------------------------------------------------------------------------------------


def test_a_registry_project_is_recognised_and_a_guide_reads_its_dependency() -> None:
    """`kind = "registry"` under [ig] and the registry table are the two roles the config exposes."""
    guide = FhirProjectConfig.model_validate(
        {
            "ig": {
                "id": "dhis2.fhir.guide",
                "canonical": _CANONICAL,
                "name": "Guide",
                "title": "Guide",
                "publisher": "P",
            },
            "generate": {"organisation_units": {"registry": _REGISTRY.model_dump(mode="json")}},
        }
    )
    package = FhirProjectConfig.model_validate(
        {
            "ig": {
                "id": "dhis2.fhir.reg",
                "canonical": _CANONICAL,
                "name": "Reg",
                "title": "Reg",
                "publisher": "P",
                "kind": "registry",
            }
        }
    )

    assert guide.is_registry_project is False
    assert guide.registry_dependency == _REGISTRY
    assert package.is_registry_project is True
    assert package.registry_dependency is None


# --- scaffold ------------------------------------------------------------------------------------

_GUIDE_OPTIONS = InitOptions(
    ig_id="dhis2.fhir.test",
    canonical=_CANONICAL,
    name="Dhis2FhirTest",
    title="DHIS2 FHIR Test IG",
    publisher="Test Organisation",
)
_DEPENDING_OPTIONS = _GUIDE_OPTIONS.model_copy(
    update={"registry": _REGISTRY.model_copy(update={"path": Path("../test-registry")})}
)
_PACKAGE_OPTIONS = _GUIDE_OPTIONS.model_copy(
    update={"ig_id": "dhis2.fhir.test.registry", "canonical": _REGISTRY.canonical, "kind": "registry", "max_level": 2}
)


def _scaffold(options: InitOptions) -> dict[str, str]:
    return {file.relative_path: file.content for file in build_scaffold_files(options)}


def test_the_dependencies_block_is_rendered_only_for_a_guide_that_names_a_registry() -> None:
    """sushi-config declares the package by its ImplementationGuide canonical and version; a plain guide none."""
    depending = yaml.safe_load(_scaffold(_DEPENDING_OPTIONS)["ig/sushi-config.yaml"])
    assert depending["dependencies"] == {
        "dhis2.fhir.test.registry": {
            "uri": "http://example.org/fhir/registry/ImplementationGuide/dhis2.fhir.test.registry",
            "version": "1.2.0",
        }
    }
    assert "dependencies" not in yaml.safe_load(_scaffold(_GUIDE_OPTIONS)["ig/sushi-config.yaml"])
    assert "dependencies" not in yaml.safe_load(_scaffold(_PACKAGE_OPTIONS)["ig/sushi-config.yaml"])


def test_the_registry_package_sushi_config_declares_the_registry_folder_and_a_two_page_menu() -> None:
    """The package ships pre-built JSON under registry/ alone, and its site is Home, Registry, Artifacts."""
    config = yaml.safe_load(_scaffold(_PACKAGE_OPTIONS)["ig/sushi-config.yaml"])
    assert config["parameters"]["path-resource"] == ["input/resources/registry/*"]
    assert list(config["menu"]) == ["Home", "Registry", "Artifacts"]
    guide = yaml.safe_load(_scaffold(_DEPENDING_OPTIONS)["ig/sushi-config.yaml"])
    assert len(guide["parameters"]["path-resource"]) == 6
    assert list(guide["menu"]) == [
        "Home",
        "Forms",
        "Registry",
        "Terminology",
        "Identifiers",
        "Periods",
        "Capture",
        "Artifacts",
    ]


def test_fhir_toml_carries_the_kind_and_the_registry_table_and_reads_both_back() -> None:
    """The scaffold writes what `read_project_scaffold_state` recovers, so a refresh reproduces the same render."""
    depending = tomllib.loads(_scaffold(_DEPENDING_OPTIONS)["fhir.toml"])
    assert depending["generate"]["organisation_units"]["registry"] == {
        "id": "dhis2.fhir.test.registry",
        "canonical": "http://example.org/fhir/registry",
        "version": "1.2.0",
        "path": "../test-registry",
    }
    assert "kind" not in depending["ig"]
    package = tomllib.loads(_scaffold(_PACKAGE_OPTIONS)["fhir.toml"])
    assert package["ig"]["kind"] == "registry"
    assert package["generate"]["organisation_units"] == {"max_level": 2}
    plain = tomllib.loads(_scaffold(_GUIDE_OPTIONS)["fhir.toml"])
    assert "organisation_units" not in plain["generate"]
    assert "kind" not in plain["ig"]


@pytest.mark.parametrize("options", [_DEPENDING_OPTIONS, _PACKAGE_OPTIONS, _GUIDE_OPTIONS])
def test_a_scaffolded_project_refreshes_to_itself(tmp_path: Path, options: InitOptions) -> None:
    """What init wrote, a refresh reads back as the very same inputs: nothing created, refreshed or diverged."""
    for file in build_scaffold_files(options, copyright_year=2026):
        destination = tmp_path / file.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(file.content, encoding="utf-8")

    state = read_project_scaffold_state(tmp_path)
    assert state.options.kind == options.kind
    assert state.options.registry == options.registry
    report = refresh_project(tmp_path)
    assert report.created_files == []
    assert report.refreshed_files == []
    assert report.diverged_files == []


def test_a_refresh_lands_the_dependencies_block_on_a_guide_that_gained_the_registry_table(tmp_path: Path) -> None:
    """Adding the table to fhir.toml and refreshing is the whole migration: sushi-config and the Makefile follow."""
    for file in build_scaffold_files(_GUIDE_OPTIONS, copyright_year=2026):
        destination = tmp_path / file.relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(file.content, encoding="utf-8")
    config_path = tmp_path / "fhir.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + '\n[generate.organisation_units.registry]\nid = "dhis2.fhir.test.registry"\n'
        'canonical = "http://example.org/fhir/registry"\nversion = "1.2.0"\npath = "../test-registry"\n',
        encoding="utf-8",
    )

    report = refresh_project(tmp_path)

    assert report.diverged_files == []
    assert "ig/sushi-config.yaml" in report.refreshed_files
    assert "Makefile" in report.refreshed_files
    sushi_config = yaml.safe_load((tmp_path / "ig" / "sushi-config.yaml").read_text(encoding="utf-8"))
    assert sushi_config["dependencies"]["dhis2.fhir.test.registry"]["version"] == "1.2.0"
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "REGISTRY_TGZ ?= ../test-registry/ig/output/package.tgz" in makefile


def test_the_makefile_installs_the_registry_package_before_sushi_and_the_publisher() -> None:
    """The three knobs follow fhir.toml, the install target fills the package cache, and both builds depend on it."""
    makefile = _scaffold(_DEPENDING_OPTIONS)["Makefile"]
    assert "REGISTRY_ID ?= dhis2.fhir.test.registry" in makefile
    assert "REGISTRY_VERSION ?= 1.2.0" in makefile
    assert "REGISTRY_TGZ ?= ../test-registry/ig/output/package.tgz" in makefile
    assert "registry-install: cache-init" in makefile
    assert "/home/publisher/.fhir/packages/$(REGISTRY_ID)#$(REGISTRY_VERSION)" in makefile
    assert "sushi: cache-init registry-install" in makefile
    assert "build: cache-init registry-install" in makefile
    assert "build-bind: cache-init registry-install" in makefile

    without_path = _scaffold(_GUIDE_OPTIONS.model_copy(update={"registry": _REGISTRY}))["Makefile"]
    assert "REGISTRY_TGZ ?= \n" in without_path
    plain = _scaffold(_GUIDE_OPTIONS)["Makefile"]
    assert "REGISTRY" not in plain
    assert "sushi: cache-init  ##" in plain
    assert "build: cache-init  ##" in plain


def test_the_front_page_of_a_guide_does_not_move_when_it_names_a_registry() -> None:
    """The registry package has its own front page; a guide's is the same file either way, so a refresh stays quiet."""
    assert (
        _scaffold(_DEPENDING_OPTIONS)["ig/input/pagecontent/index.md"]
        == _scaffold(_GUIDE_OPTIONS)["ig/input/pagecontent/index.md"]
    )
    assert (
        "This registry package is generated from DHIS2 metadata"
        in _scaffold(_PACKAGE_OPTIONS)["ig/input/pagecontent/index.md"]
    )
    assert (
        "Every organisation unit is represented as an Organization plus a Location"
        in _scaffold(_GUIDE_OPTIONS)["ig/input/pagecontent/index.md"]
    )


def test_init_options_refuse_a_registry_package_that_depends_or_publishes_forms() -> None:
    """The registry package is the registry; it names no registry and no form."""
    with pytest.raises(ValueError, match="depends on none"):
        InitOptions.model_validate({**_PACKAGE_OPTIONS.model_dump(), "registry": _REGISTRY.model_dump()})
    with pytest.raises(ValueError, match="no form"):
        InitOptions.model_validate({**_PACKAGE_OPTIONS.model_dump(), "data_set_ids": ["BfMAe6Itzgt"]})


# --- d2w fhir init --------------------------------------------------------------------------------


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run in an empty temporary working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_names_a_registry_package_through_the_registry_flags(workdir: Path) -> None:
    """`--registry-id` and `--registry-canonical` seed the table, the dependency and the Makefile knobs."""
    result = _runner.invoke(
        build_app(),
        [
            "fhir", "init", "guide",
            "--registry-id", "dhis2.fhir.test.registry",
            "--registry-canonical", "http://example.org/fhir/registry/",
            "--registry-path", "../registry",
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    raw = tomllib.loads((workdir / "guide" / "fhir.toml").read_text(encoding="utf-8"))
    assert raw["generate"]["organisation_units"]["registry"] == {
        "id": "dhis2.fhir.test.registry",
        "canonical": "http://example.org/fhir/registry",
        "version": "0.1.0",
        "path": "../registry",
    }
    sushi_config = yaml.safe_load((workdir / "guide" / "ig" / "sushi-config.yaml").read_text(encoding="utf-8"))
    assert sushi_config["dependencies"]["dhis2.fhir.test.registry"]["version"] == "0.1.0"
    assert "REGISTRY_TGZ ?= ../registry/ig/output/package.tgz" in (workdir / "guide" / "Makefile").read_text()


def test_init_scaffolds_a_registry_package_with_kind_registry(workdir: Path) -> None:
    """`--kind registry` writes `kind = "registry"` under [ig] and the two-page site."""
    result = _runner.invoke(
        build_app(),
        ["fhir", "init", "registry", "--kind", "registry", "--id", "dhis2.fhir.test.registry", "--max-level", "3"],
    )
    assert result.exit_code == 0, result.output
    raw = tomllib.loads((workdir / "registry" / "fhir.toml").read_text(encoding="utf-8"))
    assert raw["ig"]["kind"] == "registry"
    assert raw["generate"]["organisation_units"] == {"max_level": 3}
    assert load_project(workdir / "registry").config.is_registry_project


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        (["--registry-id", "dhis2.fhir.test.registry"], "both --registry-id and --registry-canonical"),
        (["--registry-version", "2.0.0"], "both --registry-id and --registry-canonical"),
        (["--kind", "registry", "--registry-id", "x", "--registry-canonical", "http://x"], "depends on no registry"),
        (["--kind", "registry", "--data-set", "BfMAe6Itzgt"], "no form"),
        (["--refresh", "--kind", "registry"], "--kind would be ignored"),
    ],
)
def test_init_refuses_a_half_named_registry_and_a_registry_package_that_depends(
    workdir: Path, arguments: list[str], fragment: str
) -> None:
    """Each refusal names the flags it is about, so a caller learns what to drop or add."""
    result = _runner.invoke(build_app(), ["fhir", "init", "project", *arguments])
    assert result.exit_code != 0
    assert fragment in " ".join(result.output.replace("│", " ").split())
    assert not (workdir / "project" / "fhir.toml").exists()


# --- generation, end to end over a mocked instance -------------------------------------------------


async def _scaffold_project(directory: Path, options: InitOptions, *extra_tables: str) -> None:
    """Scaffold a project and append whole TOML tables to its fhir.toml."""
    await service.init_project(directory, options)
    config_path = directory / "fhir.toml"
    config_path.write_text(config_path.read_text(encoding="utf-8") + "".join(extra_tables), encoding="utf-8")


def _mock_instance(
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
) -> None:
    """Mock every endpoint one full generate run reads: one data set, no programs, two units."""
    mock_system_info("v42")
    mock_attributes()
    mock_organisation_unit_levels({1: "National", 2: "District"})
    respx.get(f"{_HOST}/api/optionSets").mock(return_value=httpx.Response(200, json={"optionSets": []}))
    respx.get(f"{_HOST}/api/categories").mock(return_value=httpx.Response(200, json={"categories": []}))
    respx.get(f"{_HOST}/api/dataSets").mock(return_value=httpx.Response(200, json=_DATA_SETS_PAYLOAD))
    respx.get(f"{_HOST}/api/programs").mock(return_value=httpx.Response(200, json={"programs": []}))
    respx.get(f"{_HOST}/api/programRules").mock(return_value=httpx.Response(200, json={"programRules": []}))
    respx.get(f"{_HOST}/api/organisationUnits", name="organisationUnits").mock(
        return_value=httpx.Response(200, json=_ORGANISATION_UNITS_PAYLOAD)
    )


_REGISTRY_TABLE = (
    '\n[generate.organisation_units.registry]\nid = "dhis2.fhir.test.registry"\n'
    'canonical = "http://example.org/fhir/registry"\nversion = "1.2.0"\n'
)

_FULL_OPTIONS = InitOptions(
    ig_id="dhis2.fhir.full", canonical=_CANONICAL, name="Dhis2FhirFull", title="Full IG", publisher="Full Org"
)


def _files(root: Path, *parts: str) -> list[str]:
    directory = root.joinpath(*parts)
    return sorted(str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file())


@respx.mock
async def test_a_depending_guide_writes_no_unit_and_references_the_registry_package_absolutely(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """The org-unit directories stay empty, the hierarchy is never walked, every reference is a URL into the package."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    await _scaffold_project(tmp_path, _FULL_OPTIONS, _REGISTRY_TABLE)

    report = await service.generate_full(resolve_profile("probe"), load_project(tmp_path))

    assert _files(tmp_path, "ig", "input", "fsh", "organization") == []
    assert _files(tmp_path, "ig", "input", "resources", "registry") == []
    assert report.organisation_units.written_files == []
    assert report.organisation_units.organisation_unit_count == 2
    categories = [note.category for note in report.organisation_units.notes]
    assert categories == [GenerateNoteCategory.REGISTRY_DEPENDENCY]
    assert "dhis2.fhir.test.registry 1.2.0" in report.organisation_units.notes[0].message
    # One light read of the selection: id, code and name, never the paged hierarchy walk.
    reads = respx.routes["organisationUnits"].calls
    assert all("pageSize" not in call.request.url.params for call in reads)
    assert any(call.request.url.params.get("fields") == "id,code,name" for call in reads)
    fsh = tmp_path / "ig" / "input" / "fsh"
    assert not (fsh / "foundation" / "d2-organisation-unit-level.fsh").exists()
    examples = "".join(path.read_text(encoding="utf-8") for path in (fsh / "examples").glob("*.fsh"))
    assert "Reference(http://example.org/fhir/registry/Location/" in examples
    assert "Reference(Location/" not in examples
    (assignment_list,) = (tmp_path / "ig" / "input" / "resources" / "assignments").glob("*.json")
    assignments = json.loads(assignment_list.read_text(encoding="utf-8"))
    assert [entry["item"]["reference"] for entry in assignments["entry"]] == [
        "http://example.org/fhir/registry/Location/O6uvpzGd5pu"
    ]
    registry_page = (tmp_path / "ig" / "input" / "pagecontent" / "registry.md").read_text(encoding="utf-8")
    assert "`dhis2.fhir.test.registry` (version 1.2.0" in registry_page
    assert not list((tmp_path / "ig" / "input" / "pagecontent").glob("Organization-*"))


@respx.mock
async def test_switching_a_guide_to_a_registry_package_clears_what_the_inline_run_wrote(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """An inline run leaves profiles, instances and intros; naming the registry and rerunning deletes them all."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    await _scaffold_project(tmp_path, _FULL_OPTIONS)
    profile = resolve_profile("probe")
    inline = await service.generate_full(profile, load_project(tmp_path))
    assert "organization/profiles.fsh" in inline.organisation_units.written_files
    assert "registry/Location-O6uvpzGd5pu.json" in inline.organisation_units.written_files
    assert list((tmp_path / "ig" / "input" / "pagecontent").glob("Organization-*"))

    config_path = tmp_path / "fhir.toml"
    config_path.write_text(config_path.read_text(encoding="utf-8") + _REGISTRY_TABLE, encoding="utf-8")
    depending = await service.generate_full(profile, load_project(tmp_path))

    assert "profiles.fsh" in depending.organisation_units.deleted_files
    assert "Location-O6uvpzGd5pu.json" in depending.organisation_units.deleted_files
    assert _files(tmp_path, "ig", "input", "fsh", "organization") == []
    assert _files(tmp_path, "ig", "input", "resources", "registry") == []
    assert not list((tmp_path / "ig" / "input" / "pagecontent").glob("Organization-*"))
    assert "d2-organisation-unit-level.fsh" in depending.foundation.deleted_files


@respx.mock
async def test_the_solo_org_unit_and_pages_targets_of_a_depending_guide_match_the_full_run(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """`generate org-units` and `generate pages` take the same light read the full run takes."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    full_root = tmp_path / "full"
    solo_root = tmp_path / "solo"
    await _scaffold_project(full_root, _FULL_OPTIONS, _REGISTRY_TABLE)
    await _scaffold_project(solo_root, _FULL_OPTIONS, _REGISTRY_TABLE)
    profile = resolve_profile("probe")

    await service.generate_full(profile, load_project(full_root))
    await service.generate_foundation(load_project(solo_root))
    await service.generate_option_sets(profile, load_project(solo_root))
    await service.generate_categories(profile, load_project(solo_root))
    await service.generate_questionnaires(profile, load_project(solo_root))
    await service.generate_examples(profile, load_project(solo_root))
    solo_units = await service.generate_organisation_units(profile, load_project(solo_root))
    await service.generate_pages(profile, load_project(solo_root))

    assert solo_units.organisation_unit_count == 2
    assert solo_units.written_files == []
    full_tree = {str(p.relative_to(full_root)): p.read_bytes() for p in (full_root / "ig").rglob("*") if p.is_file()}
    solo_tree = {str(p.relative_to(solo_root)): p.read_bytes() for p in (solo_root / "ig").rglob("*") if p.is_file()}
    assert full_tree == solo_tree
    assert all("pageSize" not in call.request.url.params for call in respx.routes["organisationUnits"].calls)


@respx.mock
async def test_a_registry_package_runs_three_targets_and_refuses_the_form_side_ones(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """The package writes its foundation slice, the registry and the registry pages, and nothing of a guide's."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    options = _FULL_OPTIONS.model_copy(
        update={"ig_id": "dhis2.fhir.test.registry", "canonical": _REGISTRY.canonical, "kind": "registry"}
    )
    await _scaffold_project(tmp_path, options)
    profile = resolve_profile("probe")
    project = load_project(tmp_path)
    assert project.config.is_registry_project

    report = await service.generate_full(profile, project)

    for absent in (report.option_sets, report.categories, report.questionnaires, report.examples):
        assert absent.applies is False
        assert absent.written_files == []
        assert absent.notes == []
    assert [outcome.written_files for outcome in report.target_reports] == [
        report.foundation.written_files,
        report.organisation_units.written_files,
        report.pages.written_files,
    ]
    assert sorted(report.foundation.written_files) == [
        "foundation/d2-aliases.fsh",
        "foundation/d2-attribute-value.fsh",
        "foundation/d2-naming-systems.fsh",
        "foundation/d2-organisation-unit-level.fsh",
    ]
    assert "organization/profiles.fsh" in report.organisation_units.written_files
    assert "registry/Location-O6uvpzGd5pu.json" in report.organisation_units.written_files
    assert sorted(report.pages.written_files) == [
        "pagecontent/Organization-O6uvpzGd5pu-intro.md",
        "pagecontent/registry.md",
    ]
    assert set(_files(tmp_path, "ig", "input", "fsh")) == {
        "aliases.fsh",
        *report.foundation.written_files,
        "organization/profiles.fsh",
        "organization/org-unit-levels.fsh",
        "organization/registry-examples.fsh",
    }
    location = json.loads(
        (tmp_path / "ig" / "input" / "resources" / "registry" / "Location-O6uvpzGd5pu.json").read_text(encoding="utf-8")
    )
    assert location["meta"]["profile"] == ["http://example.org/fhir/registry/StructureDefinition/d2-location"]
    assert location["partOf"]["reference"] == "Location/ImspTQPwCqd"
    assert not (tmp_path / "ig" / "input" / "resources" / "assignments").exists()
    assert respx.routes["organisationUnits"].call_count == 1
    for target in (
        service.generate_option_sets,
        service.generate_categories,
        service.generate_questionnaires,
        service.generate_examples,
    ):
        with pytest.raises(RegistryProjectTargetError, match="registry package"):
            await target(profile, project)
    with pytest.raises(RegistryProjectTargetError, match="load-set"):
        await service.generate_load_set(profile, project)


@respx.mock
async def test_an_inline_guide_is_byte_identical_with_and_without_the_feature_in_the_tree(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """A guide that names no registry publishes relative references, its own profiles, and the level extension."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    await _scaffold_project(tmp_path, _FULL_OPTIONS)

    report = await service.generate_full(resolve_profile("probe"), load_project(tmp_path))

    assert all(outcome.applies for outcome in report.target_reports)
    assert len(report.target_reports) == 7
    assert "foundation/d2-organisation-unit-level.fsh" in report.foundation.written_files
    assert "organization/profiles.fsh" in report.organisation_units.written_files
    fsh = tmp_path / "ig" / "input" / "fsh"
    examples = "".join(path.read_text(encoding="utf-8") for path in (fsh / "examples").glob("*.fsh"))
    assert re.search(r"Reference\(Location/[A-Za-z0-9]{11}\)", examples)
    assert "http://example.org/fhir/registry" not in examples
    assert "* subject only Reference(D2Location)" in (fsh / "foundation" / "d2-responses.fsh").read_text(
        encoding="utf-8"
    )
