"""What `d2w fhir forward` resolves a unit reference through when another package publishes the units.

Both halves of the command are here, because the point is that they agree: the compiled half reads
the guide off disk and the live half builds it off the instance, and a guide naming
`[generate.organisation_units.registry]` gets its places out of the registry package either way.

Mocked (respx); no live stack. The instance carries two organisation units the registry does not
publish, so a run that walked the hierarchy is told apart from one that read the package by the
Location ids that come back.
"""

from __future__ import annotations

import json
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from dhis2w_core.client_context import open_client
from dhis2w_core.profile import resolve_profile
from dhis2w_fhir import CompiledArtifacts, load_project, service
from dhis2w_fhir.conversion import load_compiled_artifacts
from dhis2w_fhir.registry_package import RegistryMissingError

_HOST = "https://dhis2.example"

_CANONICAL = "http://example.org/fhir"

_REGISTRY_ID = "dhis2.fhir.pair.registry"

_REGISTRY_CANONICAL = "http://example.org/fhir/pair/registry"

#: The place the registry package publishes, which the instance's hierarchy does not hold.
_PACKAGED_UNIT = "Vth0fbpFcsO"

#: The places the instance holds, which a guide depending on a registry publishes none of.
_INSTANCE_UNITS = ("ImspTQPwCqd", "O6uvpzGd5pu")

_GUIDE_TOML = f"""
[ig]
id = "dhis2.fhir.pair"
canonical = "{_CANONICAL}"
name = "Dhis2FhirPair"
title = "Pair guide"
publisher = "Example Organisation"
"""

_REGISTRY_TABLE = f"""
[generate.organisation_units.registry]
id = "{_REGISTRY_ID}"
canonical = "{_REGISTRY_CANONICAL}"
version = "0.1.0"
"""

_OPTION_SETS_PAYLOAD: dict[str, list[dict[str, Any]]] = {"optionSets": []}

_CATEGORIES_PAYLOAD: dict[str, list[dict[str, Any]]] = {"categories": []}

_ORGANISATION_UNITS_PAYLOAD = {
    "organisationUnits": [
        {"id": "ImspTQPwCqd", "name": "Sierra Leone", "level": 1, "path": "/ImspTQPwCqd", "code": "SL"},
        {
            "id": "O6uvpzGd5pu",
            "name": "Bo",
            "level": 2,
            "path": "/ImspTQPwCqd/O6uvpzGd5pu",
            "parent": {"id": "ImspTQPwCqd"},
        },
    ]
}

_DATA_SETS_PAYLOAD = {
    "dataSets": [
        {
            "id": "BfMAe6Itzgt",
            "name": "Child Health",
            "code": "DS_359711",
            "organisationUnits": [{"id": "ImspTQPwCqd"}],
            "sections": [{"id": "Sec1aaaaaaa", "name": "Immunization", "dataElements": [{"id": "De1aaaaaaaa"}]}],
            "dataSetElements": [
                {
                    "dataElement": {
                        "id": "De1aaaaaaaa",
                        "name": "BCG doses given",
                        "valueType": "INTEGER_ZERO_OR_POSITIVE",
                        "domainType": "AGGREGATE",
                        "categoryCombo": {"id": "bjDvmb4bfuf", "name": "default", "isDefault": True},
                    }
                }
            ],
        }
    ]
}


def _mock_instance(
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
) -> None:
    """Mock every endpoint a live forward reads off the instance."""
    mock_system_info("v43")
    mock_attributes()
    mock_organisation_unit_levels()
    respx.get(f"{_HOST}/api/optionSets").mock(return_value=httpx.Response(200, json=_OPTION_SETS_PAYLOAD))
    respx.get(f"{_HOST}/api/categories").mock(return_value=httpx.Response(200, json=_CATEGORIES_PAYLOAD))
    respx.get(f"{_HOST}/api/dataSets").mock(return_value=httpx.Response(200, json=_DATA_SETS_PAYLOAD))
    respx.get(f"{_HOST}/api/programs").mock(return_value=httpx.Response(200, json={"programs": []}))
    respx.get(f"{_HOST}/api/programRules").mock(return_value=httpx.Response(200, json={"programRules": []}))
    respx.get(f"{_HOST}/api/organisationUnits").mock(return_value=httpx.Response(200, json=_ORGANISATION_UNITS_PAYLOAD))


def _guide(root: Path, *, registry: bool, path: str | None = None) -> Path:
    """Write a guide project, optionally depending on a registry package a checkout answers for."""
    root.mkdir(parents=True, exist_ok=True)
    body = _GUIDE_TOML
    if registry:
        body += _REGISTRY_TABLE
        if path is not None:
            body += f'path = "{path}"\n'
    (root / "fhir.toml").write_text(body, encoding="utf-8")
    return root


def _registry_checkout(root: Path) -> Path:
    """The registry project beside the guide, holding the one place it publishes."""
    directory = root / "ig" / "input" / "resources" / "registry"
    directory.mkdir(parents=True, exist_ok=True)
    for resource_type in ("Location", "Organization"):
        (directory / f"{resource_type}-{_PACKAGED_UNIT}.json").write_text(
            json.dumps(
                {
                    "resourceType": resource_type,
                    "id": _PACKAGED_UNIT,
                    "name": "Ngelehun CHC",
                    "identifier": [{"system": "http://dhis2.org/fhir/id/org-unit", "value": _PACKAGED_UNIT}],
                }
            ),
            encoding="utf-8",
        )
    return directory


def _tarball(destination: Path, *, source: Path) -> Path:
    """Pack a directory the way the IG publisher packs `package.tgz`, rooted at `package/`.

    The registry's own `package.tgz` comes out of `make build`, which runs the IG publisher - so the
    hand-off source is exercised here against an archive of the same shape rather than a built one.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(source.rglob("*.json")):
            archive.add(path, arcname=f"package/{path.name}")
    return destination


def _compiled_guide(root: Path) -> Path:
    """The one compiled resource that makes a project's own guide readable off disk."""
    directory = root / "ig" / "fsh-generated" / "resources"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "Questionnaire-BfMAe6Itzgt.json").write_text(
        json.dumps(
            {
                "resourceType": "Questionnaire",
                "id": "BfMAe6Itzgt",
                "url": f"{_CANONICAL}/Questionnaire/BfMAe6Itzgt",
                "status": "active",
            }
        ),
        encoding="utf-8",
    )
    return directory


async def _live_artifacts(root: Path, *, registry_package: Path | None = None) -> CompiledArtifacts:
    """Build the forward-side artifacts off the mocked instance, the way a drain with no build does."""
    async with open_client(resolve_profile("probe")) as client:
        return await service.fetch_live_artifacts(client, load_project(root), registry_package=registry_package)


def _location_ids(artifacts: CompiledArtifacts) -> list[str]:
    """The places a `Location/<id>` reference in a receipt can resolve against."""
    return sorted(location.id for location in artifacts.locations if location.id is not None)


@respx.mock
async def test_a_live_forward_resolves_its_places_through_the_registry_the_guide_depends_on(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """The hierarchy is not walked and no place of this guide's own is built: the package answers.

    Building the instance's units here would resolve a receipt's reference through a place the
    published guide does not publish, so a drain with no build step would accept what a drain
    reading the compiled guide refuses.
    """
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    _registry_checkout(tmp_path / "registry")

    artifacts = await _live_artifacts(_guide(tmp_path / "guide", registry=True, path="../registry"))

    assert _location_ids(artifacts) == [_PACKAGED_UNIT]


@respx.mock
async def test_a_live_forward_reaching_no_registry_refuses_before_it_reads_the_instance(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """A package neither source supplies is a refusal naming both remedies, not a fall-back."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    project = _guide(tmp_path / "guide", registry=True, path="../registry")

    with pytest.raises(RegistryMissingError, match=_REGISTRY_ID):
        await _live_artifacts(project)


@respx.mock
async def test_a_live_forward_reads_the_registry_out_of_the_package_named_on_the_command_line(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """`--registry-package` is the hand-off case: the checkout is gone and the archive answers."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    checkout = _registry_checkout(tmp_path / "registry")
    package = _tarball(tmp_path / "package.tgz", source=checkout)
    checkout.rename(tmp_path / "moved-registry")

    artifacts = await _live_artifacts(
        _guide(tmp_path / "guide", registry=True, path="../registry"), registry_package=package
    )

    assert _location_ids(artifacts) == [_PACKAGED_UNIT]


@respx.mock
async def test_a_live_forward_of_a_guide_publishing_its_own_places_still_builds_them_off_the_instance(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """A guide naming no registry table is unchanged: its places are the instance's, built here."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)

    artifacts = await _live_artifacts(_guide(tmp_path / "guide", registry=False))

    assert _location_ids(artifacts) == sorted(_INSTANCE_UNITS)


@respx.mock
async def test_the_compiled_and_the_live_half_of_one_forward_publish_the_same_places(
    probe_profile: None,  # noqa: ARG001
    mock_system_info: Callable[..., None],
    mock_attributes: Callable[..., None],
    mock_organisation_unit_levels: Callable[..., None],
    tmp_path: Path,
) -> None:
    """One project, one registry, one answer - whether the guide was read off disk or built live."""
    _mock_instance(mock_system_info, mock_attributes, mock_organisation_unit_levels)
    _registry_checkout(tmp_path / "registry")
    root = _guide(tmp_path / "guide", registry=True, path="../registry")
    _compiled_guide(root)

    compiled = load_compiled_artifacts(load_project(root))
    live = await _live_artifacts(root)

    assert _location_ids(compiled) == _location_ids(live) == [_PACKAGED_UNIT]
