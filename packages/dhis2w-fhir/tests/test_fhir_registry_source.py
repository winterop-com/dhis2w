"""Reading the organisation-unit registry a depending guide's units live in.

Two sources in a fixed order - the configured checkout, then a package named on the command line -
and a refusal naming both when neither answers. A guide publishing its registry inline declares no
registry at all and never reaches any of this, which is what the first test pins.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
from dhis2w_fhir.config import load_project
from dhis2w_fhir.registry_package import (
    REGISTRY_PACKAGE_RESOURCE_TYPES,
    RegistryMissingError,
    load_registry_documents,
    resolve_registry_source,
)
from dhis2w_fhir.validation.artifacts import ArtifactFinding, check_publishable_artifacts

_CANONICAL = "http://example.org/fhir"
_REGISTRY_CANONICAL = "http://example.org/fhir/registry"
_REGISTRY_ID = "dhis2.fhir.example.registry"

_GUIDE_TOML = f"""
[ig]
id = "dhis2.fhir.example"
canonical = "{_CANONICAL}"
name = "Example"
title = "Example guide"
publisher = "Example Org"
"""

_REGISTRY_TABLE = f"""
[generate.organisation_units.registry]
id = "{_REGISTRY_ID}"
canonical = "{_REGISTRY_CANONICAL}"
version = "1.2.0"
"""


def _resource(resource_type: str, resource_id: str) -> dict[str, object]:
    """One organisation-unit resource as the registry publishes it."""
    return {
        "resourceType": resource_type,
        "id": resource_id,
        "meta": {"profile": [f"{_REGISTRY_CANONICAL}/StructureDefinition/d2-location"]},
        "identifier": [{"system": "http://dhis2.org/fhir/id/org-unit", "value": resource_id}],
    }


def _write_resources(directory: Path, *, extra_types: bool = False) -> None:
    """Write the two resources a unit is published as, plus optionally what a package also ships."""
    directory.mkdir(parents=True, exist_ok=True)
    for resource_type in ("Location", "Organization"):
        for uid in ("ImspTQPwCqd", "O6uvpzGd5pu"):
            (directory / f"{resource_type}-{uid}.json").write_text(
                json.dumps(_resource(resource_type, uid)), encoding="utf-8"
            )
    if extra_types:
        (directory / "ImplementationGuide-x.json").write_text(
            json.dumps({"resourceType": "ImplementationGuide", "id": "x"}), encoding="utf-8"
        )
        (directory / "StructureDefinition-d2-location.json").write_text(
            json.dumps({"resourceType": "StructureDefinition", "id": "d2-location"}), encoding="utf-8"
        )


def _guide(root: Path, *, registry: bool, path: str | None = None) -> Path:
    """Write a guide project, optionally depending on a registry package."""
    root.mkdir(parents=True, exist_ok=True)
    body = _GUIDE_TOML
    if registry:
        body += _REGISTRY_TABLE
        if path is not None:
            body += f'path = "{path}"\n'
    (root / "fhir.toml").write_text(body, encoding="utf-8")
    return root


def _checkout(root: Path, *, generated: bool = True) -> Path:
    """A checkout of the registry project beside the guide, generated or not yet."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "fhir.toml").write_text(
        _GUIDE_TOML.replace("dhis2.fhir.example", _REGISTRY_ID).replace(_CANONICAL, _REGISTRY_CANONICAL),
        encoding="utf-8",
    )
    if generated:
        _write_resources(root / "ig" / "input" / "resources" / "registry")
    return root


def _tarball(destination: Path, *, source: Path) -> Path:
    """Pack a directory the way the IG publisher packs `package.tgz`, rooted at `package/`."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(source.rglob("*.json")):
            archive.add(path, arcname=f"package/{path.name}")
    return destination


# --- a guide that publishes its registry inline never reaches any of this ------------------------


def test_a_guide_without_the_registry_table_resolves_no_source_and_reads_nothing(tmp_path: Path) -> None:
    """The opt-in stays opt-in: the inline guide's own predefined tree is the caller's to read."""
    project = load_project(_guide(tmp_path / "guide", registry=False))

    assert resolve_registry_source(project) is None
    assert load_registry_documents(project) == []
    # Even a package named on the command line is nothing to a guide that publishes its own units.
    assert load_registry_documents(project, package=tmp_path / "nowhere.tgz") == []


# --- the checkout, which is the everyday case ----------------------------------------------------


def test_the_configured_checkout_supplies_the_units(tmp_path: Path) -> None:
    """`registry.path` names a sibling project, and its generated registry is read without any build."""
    _checkout(tmp_path / "registry")
    project = load_project(_guide(tmp_path / "guide", registry=True, path="../registry"))

    source = resolve_registry_source(project)
    assert source is not None
    assert source.kind == "checkout"
    assert source.location.name == "registry"

    documents = load_registry_documents(project)
    assert len(documents) == 4
    assert {document.body["resourceType"] for document in documents} == REGISTRY_PACKAGE_RESOURCE_TYPES
    assert {document.body["id"] for document in documents} == {"ImspTQPwCqd", "O6uvpzGd5pu"}
    assert all(document.source.endswith(".json") for document in documents)


def test_the_checkout_is_read_before_a_package_given_on_the_command_line(tmp_path: Path) -> None:
    """Two projects side by side keep working off the files on disk, build or no build."""
    _checkout(tmp_path / "registry")
    package = _tarball(tmp_path / "dist" / "package.tgz", source=tmp_path / "registry" / "ig" / "input" / "resources")
    project = load_project(_guide(tmp_path / "guide", registry=True, path="../registry"))

    source = resolve_registry_source(project, package=package)

    assert source is not None
    assert source.kind == "checkout"


# --- the package, which is the hand-off case -----------------------------------------------------


@pytest.mark.parametrize("rooted", [True, False])
def test_a_package_directory_supplies_the_units_rooted_either_way(tmp_path: Path, rooted: bool) -> None:
    """An extracted package carries `package/`; a directory of bare resources is taken as it is."""
    extracted = tmp_path / "extracted"
    _write_resources(extracted / "package" if rooted else extracted, extra_types=True)
    project = load_project(_guide(tmp_path / "guide", registry=True))

    documents = load_registry_documents(project, package=extracted)

    assert len(documents) == 4
    # The package also ships its profiles and its own ImplementationGuide; a guide reads neither.
    assert {document.body["resourceType"] for document in documents} == REGISTRY_PACKAGE_RESOURCE_TYPES


def test_a_package_tarball_is_read_in_place(tmp_path: Path) -> None:
    """The archive `make build` wrote is read without being extracted, and names its member in the source."""
    staged = tmp_path / "staged"
    _write_resources(staged, extra_types=True)
    package = _tarball(tmp_path / "dist" / "package.tgz", source=staged)
    project = load_project(_guide(tmp_path / "guide", registry=True))

    source = resolve_registry_source(project, package=package)
    documents = load_registry_documents(project, package=package)

    assert source is not None
    assert source.kind == "package"
    assert len(documents) == 4
    assert all(document.source.startswith(f"{package}:package/") for document in documents)
    assert not (tmp_path / "dist" / "package").exists(), "the archive was extracted to disk"


def _write_example_pair(package_root: Path) -> None:
    """The worked `d2-example` pair a built registry ships under `package/example/`."""
    example = package_root / "example"
    example.mkdir(parents=True, exist_ok=True)
    for resource_type in ("Location", "Organization"):
        (example / f"{resource_type}-d2-example.json").write_text(
            json.dumps(_resource(resource_type, "d2-example")), encoding="utf-8"
        )


def test_a_package_tarball_reads_its_top_level_and_not_its_examples(tmp_path: Path) -> None:
    """The example pair names no organisation unit, so the tarball serves the units the checkout does."""
    staged = tmp_path / "staged"
    _write_resources(staged)
    _write_example_pair(staged)
    package = tmp_path / "dist" / "package.tgz"
    package.parent.mkdir(parents=True)
    with tarfile.open(package, "w:gz") as archive:
        for path in sorted(staged.rglob("*.json")):
            archive.add(path, arcname=f"package/{path.relative_to(staged).as_posix()}")
    project = load_project(_guide(tmp_path / "guide", registry=True))

    documents = load_registry_documents(project, package=package)

    assert len(documents) == 4
    assert not any("d2-example" in document.source for document in documents)


def test_an_extracted_package_reads_its_top_level_and_not_its_examples(tmp_path: Path) -> None:
    """The same rule for a package unpacked to a directory as for the archive read in place."""
    extracted = tmp_path / "extracted"
    _write_resources(extracted / "package")
    _write_example_pair(extracted / "package")
    project = load_project(_guide(tmp_path / "guide", registry=True))

    documents = load_registry_documents(project, package=extracted)

    assert len(documents) == 4
    assert not any("d2-example" in document.source for document in documents)


# --- the refusals --------------------------------------------------------------------------------


def test_neither_source_refuses_and_names_both_remedies(tmp_path: Path) -> None:
    """A guide that can reach no registry refuses rather than serving a hierarchy of nothing."""
    project = load_project(_guide(tmp_path / "guide", registry=True))

    with pytest.raises(RegistryMissingError) as error:
        resolve_registry_source(project)

    message = str(error.value)
    assert _REGISTRY_ID in message
    assert "1.2.0" in message
    assert "path" in message
    assert "--registry-package" in message


def test_a_checkout_that_has_not_generated_yet_says_which_command_fills_it(tmp_path: Path) -> None:
    """`path` pointing at a project with no generated registry names `d2w fhir generate`, not a missing flag."""
    _checkout(tmp_path / "registry", generated=False)
    project = load_project(_guide(tmp_path / "guide", registry=True, path="../registry"))

    with pytest.raises(RegistryMissingError) as error:
        resolve_registry_source(project)

    message = str(error.value)
    assert "../registry" in message
    assert "d2w fhir generate" in message
    assert "--registry-package" in message


def test_a_package_that_is_not_there_is_named(tmp_path: Path) -> None:
    """A mistyped `--registry-package` says so about the path given, not about the configuration."""
    project = load_project(_guide(tmp_path / "guide", registry=True))

    with pytest.raises(RegistryMissingError, match="no such file or directory"):
        resolve_registry_source(project, package=tmp_path / "absent.tgz")


def test_a_package_holding_no_organisation_unit_refuses(tmp_path: Path) -> None:
    """An archive of the wrong thing is a refusal naming the package, not an empty hierarchy."""
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "ImplementationGuide-x.json").write_text(
        json.dumps({"resourceType": "ImplementationGuide", "id": "x"}), encoding="utf-8"
    )
    project = load_project(_guide(tmp_path / "guide", registry=True))

    with pytest.raises(RegistryMissingError, match="holds no organisation-unit resource"):
        load_registry_documents(project, package=empty)


def test_a_resource_that_is_not_json_fails_loudly_and_names_the_file(tmp_path: Path) -> None:
    """A silently skipped resource reads to a client as a unit the registry never published."""
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "Location-x.json").write_text("{not json", encoding="utf-8")
    project = load_project(_guide(tmp_path / "guide", registry=True))

    with pytest.raises(RegistryMissingError, match="not valid JSON"):
        load_registry_documents(project, package=broken)


def test_a_bad_archive_is_named_rather_than_read_as_empty(tmp_path: Path) -> None:
    """A truncated or non-archive file refuses by name instead of resolving to no units."""
    package = tmp_path / "package.tgz"
    package.write_bytes(b"not a tarball at all")
    project = load_project(_guide(tmp_path / "guide", registry=True))

    with pytest.raises(RegistryMissingError, match="not a readable package archive"):
        load_registry_documents(project, package=package)


# --- check-artifacts: a reference the registry package does not publish --------------------------


def _guide_with_references(root: Path, *, stems: list[str], path: str | None = "../registry") -> Path:
    """A guide on disk whose examples and assignment Lists reference units in the registry package."""
    _guide(root, registry=True, path=path)
    compiled = root / "ig" / "fsh-generated" / "resources"
    compiled.mkdir(parents=True, exist_ok=True)
    (compiled / "List-d2-ds-x-org-units.json").write_text(
        json.dumps(
            {
                "resourceType": "List",
                "id": "d2-ds-x-org-units",
                "entry": [{"item": {"reference": f"{_REGISTRY_CANONICAL}/Location/{stem}"}} for stem in stems],
            }
        ),
        encoding="utf-8",
    )
    fsh = root / "ig" / "input" / "fsh" / "examples"
    fsh.mkdir(parents=True, exist_ok=True)
    (fsh / "response.fsh").write_text(
        "Instance: Example\n"
        "InstanceOf: QuestionnaireResponse\n"
        f"* subject = Reference({_REGISTRY_CANONICAL}/Location/{stems[0]})\n",
        encoding="utf-8",
    )
    return root


def _registry_findings_of(root: Path, *, registry_package: Path | None = None) -> list[ArtifactFinding]:
    """Run the artifact scan and keep only what it says about the registry."""
    report = check_publishable_artifacts(load_project(root), registry_package=registry_package)
    return [finding for finding in report.findings if finding.kind == "registry"]


def test_a_guide_whose_references_the_registry_publishes_raises_nothing(tmp_path: Path) -> None:
    """The everyday case: both projects generated off one instance, every reference resolvable."""
    _checkout(tmp_path / "registry")
    root = _guide_with_references(tmp_path / "guide", stems=["ImspTQPwCqd", "O6uvpzGd5pu"])

    assert _registry_findings_of(root) == []


def test_a_reference_the_registry_does_not_publish_is_a_finding(tmp_path: Path) -> None:
    """The two selections have gone apart, which the publisher would only say after rendering everything."""
    _checkout(tmp_path / "registry")
    root = _guide_with_references(tmp_path / "guide", stems=["ImspTQPwCqd", "Zz9Zz9Zz9Zz"])

    findings = _registry_findings_of(root)

    values = {finding.value for finding in findings}
    assert values == {f"{_REGISTRY_CANONICAL}/Location/Zz9Zz9Zz9Zz"}
    finding = findings[0]
    assert finding.file == "ig/fsh-generated/resources/List-d2-ds-x-org-units.json"
    assert "does not publish" in finding.message
    assert "regenerate both projects" in finding.remedy


def test_an_fsh_reference_the_registry_does_not_publish_is_found_too(tmp_path: Path) -> None:
    """Generated FSH states the same references, and a scan that read only JSON would pass them."""
    _checkout(tmp_path / "registry")
    root = _guide_with_references(tmp_path / "guide", stems=["Yy8Yy8Yy8Yy"])

    files = {finding.file for finding in _registry_findings_of(root)}

    assert "ig/input/fsh/examples/response.fsh" in files


def test_a_registry_the_scan_cannot_read_is_one_finding_naming_the_config(tmp_path: Path) -> None:
    """A build against an uninstalled package fails on every reference, so the scan says it once."""
    root = _guide_with_references(tmp_path / "guide", stems=["ImspTQPwCqd"], path=None)

    findings = _registry_findings_of(root)

    assert len(findings) == 1
    assert findings[0].file == "fhir.toml"
    assert "--registry-package" in findings[0].remedy


def test_the_package_flag_supplies_the_registry_to_the_scan(tmp_path: Path) -> None:
    """With no checkout, the archive answers the scan exactly as it answers the facade."""
    staged = tmp_path / "staged"
    _write_resources(staged)
    package = _tarball(tmp_path / "dist" / "package.tgz", source=staged)
    root = _guide_with_references(tmp_path / "guide", stems=["ImspTQPwCqd"], path=None)

    assert _registry_findings_of(root, registry_package=package) == []


def test_an_inline_guide_is_never_asked_about_a_registry(tmp_path: Path) -> None:
    """A guide publishing its own units declares no registry, so the whole comparison is skipped."""
    root = _guide(tmp_path / "guide", registry=False)
    compiled = root / "ig" / "fsh-generated" / "resources"
    compiled.mkdir(parents=True, exist_ok=True)
    (compiled / "List-x.json").write_text(
        json.dumps({"resourceType": "List", "id": "x", "entry": [{"item": {"reference": "Location/ImspTQPwCqd"}}]}),
        encoding="utf-8",
    )

    assert _registry_findings_of(root) == []
