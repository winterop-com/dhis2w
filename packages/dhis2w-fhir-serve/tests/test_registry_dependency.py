"""Serving a guide whose organisation units are published by a registry package.

The facade's contract does not change: a `Location` read answers the same way whether the guide
published the unit itself or depends on a package for it. What changes is where the store found it,
and that a guide which can reach no registry refuses before it starts rather than serving a
hierarchy with no places in it.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
from dhis2w_fhir.config import FhirProject, load_fhir_config
from dhis2w_fhir.registry_package import RegistryMissingError
from dhis2w_fhir_serve.settings import ServeSettings
from dhis2w_fhir_serve.store import load_compiled_store

_CANONICAL = "http://example.org/fhir"

_MINIMAL_FHIR_TOML = f"""
[ig]
id = "dhis2.fhir.example"
canonical = "{_CANONICAL}"
name = "Dhis2FhirExample"
title = "DHIS2 FHIR Example IG"
publisher = "Example Organisation"
"""

_REGISTRY_CANONICAL = f"{_CANONICAL}/registry"
_REGISTRY_ID = "dhis2.fhir.example.registry"
_UNIT = "ImspTQPwCqd"

_REGISTRY_TABLE = f"""
[generate.organisation_units.registry]
id = "{_REGISTRY_ID}"
canonical = "{_REGISTRY_CANONICAL}"
version = "0.1.0"
"""


def _location(uid: str) -> dict[str, object]:
    """One published place, as the registry package carries it."""
    return {
        "resourceType": "Location",
        "id": uid,
        "meta": {"profile": [f"{_REGISTRY_CANONICAL}/StructureDefinition/d2-location"]},
        "name": "Sierra Leone",
        "identifier": [{"system": "http://dhis2.org/fhir/id/org-unit", "value": uid}],
    }


def _depending_project(root: Path, *, path: str | None = None) -> FhirProject:
    """A guide with a compiled IG, an empty registry directory of its own, and a declared registry package."""
    config_path = root / "fhir.toml"
    body = _MINIMAL_FHIR_TOML + _REGISTRY_TABLE
    if path is not None:
        body += f'path = "{path}"\n'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(body, encoding="utf-8")
    compiled = root / "ig" / "fsh-generated" / "resources"
    compiled.mkdir(parents=True, exist_ok=True)
    (compiled / "Questionnaire-q.json").write_text(
        json.dumps({"resourceType": "Questionnaire", "id": "q", "status": "active"}), encoding="utf-8"
    )
    # The guide's own registry directory exists and is empty, which is what generate leaves behind.
    (root / "ig" / "input" / "resources" / "registry").mkdir(parents=True, exist_ok=True)
    return FhirProject(config=load_fhir_config(config_path), config_path=config_path.resolve())


def _checkout(root: Path) -> Path:
    """A generated checkout of the registry project."""
    directory = root / "ig" / "input" / "resources" / "registry"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"Location-{_UNIT}.json").write_text(json.dumps(_location(_UNIT)), encoding="utf-8")
    return root


def _package(destination: Path) -> Path:
    """The `package.tgz` the registry project's own build wrote."""
    staged = destination.parent / "staged"
    staged.mkdir(parents=True, exist_ok=True)
    resource = staged / f"Location-{_UNIT}.json"
    resource.write_text(json.dumps(_location(_UNIT)), encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(resource, arcname=f"package/{resource.name}")
    return destination


def test_the_store_serves_a_unit_out_of_the_checkout(tmp_path: Path) -> None:
    """A place the guide publishes no file for is still readable, because the package publishes it."""
    _checkout(tmp_path / "registry")
    project = _depending_project(tmp_path / "guide", path="../registry")

    store = load_compiled_store(project)

    entry = store.by_type_and_id("Location", _UNIT)
    assert entry is not None
    assert entry.body["name"] == "Sierra Leone"
    assert entry.resource_type == "Location"


def test_the_store_serves_a_unit_out_of_a_package_archive(tmp_path: Path) -> None:
    """The hand-off case: no checkout, the archive named on the command line answers instead."""
    package = _package(tmp_path / "dist" / "package.tgz")
    project = _depending_project(tmp_path / "guide")

    store = load_compiled_store(project, registry_package=package)

    entry = store.by_type_and_id("Location", _UNIT)
    assert entry is not None
    assert entry.source.startswith(str(package))


def test_a_guide_reaching_no_registry_refuses_rather_than_serving_no_place(tmp_path: Path) -> None:
    """Serving zero organisation units reads to a client as an instance with none, so it is refused."""
    project = _depending_project(tmp_path / "guide")

    with pytest.raises(RegistryMissingError, match=_REGISTRY_ID):
        load_compiled_store(project)


def test_the_preflight_refuses_before_the_server_starts(tmp_path: Path) -> None:
    """The refusal lands while resolving settings, so it is not printed under a starting banner."""
    project = _depending_project(tmp_path / "guide")

    with pytest.raises(RegistryMissingError):
        ServeSettings.resolve(project)


def test_the_preflight_passes_once_the_registry_is_reachable(tmp_path: Path) -> None:
    """With a checkout in place the run resolves, and the package stays unset because none was needed."""
    _checkout(tmp_path / "registry")
    project = _depending_project(tmp_path / "guide", path="../registry")

    invocation = ServeSettings.resolve(project)

    assert invocation.settings.registry_package is None


_PROFILES_TOML = """
default = "probe"

[profiles.probe]
base_url = "https://dhis2.example"
auth = "basic"
username = "admin"
password = "district"
"""


@pytest.fixture
def resolvable_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile this test can resolve, from a config home of its own.

    A live run requires one, and the machine running the suite must not be what supplies it: a
    developer with a profile configured would pass while CI, which has none, would not.
    """
    config_directory = tmp_path / ".config" / "dhis2"
    config_directory.mkdir(parents=True, exist_ok=True)
    (config_directory / "profiles.toml").write_text(_PROFILES_TOML, encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_directory.parent))
    monkeypatch.delenv("DHIS2_PROFILE", raising=False)


def test_a_live_run_needs_no_registry_package(
    tmp_path: Path,
    resolvable_profile: None,  # noqa: ARG001 - the fixture is the environment this test needs
) -> None:
    """`--live` builds its units off the instance, so the registry package is nothing to it.

    The guide here declares a registry and can reach neither source, which a compiled run refuses
    on; a live run resolves anyway, which is what says the preflight is skipped rather than passed.
    """
    project = _depending_project(tmp_path / "guide")

    invocation = ServeSettings.resolve(project, live=True)

    assert invocation.settings.live is True
    assert invocation.settings.registry_package is None


def test_the_package_reaches_the_settings_for_the_runtime_to_load_from(tmp_path: Path) -> None:
    """What the flag named is carried onto the settings, which is what the store reads it off."""
    package = _package(tmp_path / "dist" / "package.tgz")
    project = _depending_project(tmp_path / "guide")

    invocation = ServeSettings.resolve(project, registry_package=package)

    assert invocation.settings.registry_package == package
