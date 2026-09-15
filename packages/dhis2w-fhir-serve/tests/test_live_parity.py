"""One guide, two stores: what `--live` builds off an instance and what a generate writes to disk agree.

`dhis2w_fhir_serve.live.build_live_store` and `dhis2w_fhir.service.generate_full` are twins. Both
read one instance through `fetch_live_ig_inputs` and hand the result to the same JSON builders, so
every artifact a compiled project commits under `ig/input/resources` is an artifact the live store
serves - same resource, same id, same bytes. The two call sites are written by hand, though, and a
keyword one of them stops passing is a whole family of documents the other publishes and this one
does not, with nothing failing anywhere.

So this module holds them to the artifact set rather than to a list of keywords: the instance is
mocked once, both stores are built off it, and every predefined file the disk run wrote has to come
back out of the live store byte for byte. The three resource types that exist only as predefined
JSON - `List`, `Location`, `Organization` - are compared as whole sets in both directions, so an
artifact the live store invents is caught beside one it drops.

The fixture is shaped for the three things a thin one would miss. An attribute option combo whose
category options DHIS2 restricts to particular organisation units, so the restriction Lists and the
`dhis2-organisation-units` concept property are in play. A published registry, so the Locations and
Organizations are there to be named. And a form whose DHIS2 assignment names no published unit, so
the empty assignment List is written too.

Mocked (respx); no live stack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from dhis2w_core.client_context import open_client
from dhis2w_fhir.config import FhirProject, load_fhir_config
from dhis2w_fhir.service import generate_full, resolve_generation_profile
from dhis2w_fhir_serve.live import build_live_store
from dhis2w_fhir_serve.settings import ServeSettings
from dhis2w_fhir_serve.store import ResourceStore

_HOST = "https://dhis2.example"

_CANONICAL = "http://example.org/fhir/parity"

#: The three resource types a guide publishes as predefined JSON and never as compiled FSH.
#:
#: Every other type in the store is published both ways - the foundation pairs are FSH a live run
#: rebuilds in Python - so these are the three whose two sides can be compared as whole sets.
_PREDEFINED_ONLY_RESOURCE_TYPES = ("List", "Location", "Organization")

_FHIR_TOML = f"""
[ig]
id = "dhis2.fhir.parity"
canonical = "{_CANONICAL}"
name = "Dhis2FhirParity"
title = "DHIS2 FHIR Parity Guide"
publisher = "Example Organisation"

[generate.examples]
per_target = 0
"""

_PROFILES_TOML = """
default = "probe"

[profiles.probe]
base_url = "https://dhis2.example"
auth = "basic"
username = "admin"
password = "district"
"""

_SYSTEM_INFO = {"version": "2.43.0"}

#: The registry this guide publishes: the national root and one district under it.
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

_ORGANISATION_UNIT_LEVELS_PAYLOAD = {
    "organisationUnitLevels": [
        {"id": "OlParity0001", "level": 1, "name": "National"},
        {"id": "OlParity0002", "level": 2, "name": "District"},
    ]
}

#: The category the attribute combo is met from, and the two options it is met from.
_CATEGORIES_PAYLOAD = {
    "categories": [
        {
            "id": "yY2bQYqNt0o",
            "name": "Project",
            "categoryOptions": [
                {"id": "i4Nbp8S2G6A", "code": "WATER", "name": "Improve access to clean water"},
                {"id": "M58XdOfhiJ7", "code": "SCHOOL", "name": "Provide access to basic education"},
            ],
        }
    ]
}

#: What DHIS2 scopes each of those two category options to.
#:
#: `i4Nbp8S2G6A` names a unit this guide publishes none of, so its List is published empty - the
#: combos met from it are usable nowhere here. `M58XdOfhiJ7` names the district, which narrows the
#: registry to one of its two units, so its List names that one. Between them they cover both
#: outcomes a restriction can have.
_CATEGORY_OPTIONS_PAYLOAD = {
    "categoryOptions": [
        {"id": "i4Nbp8S2G6A", "organisationUnits": [{"id": "GvFqTavdpGE"}]},
        {"id": "M58XdOfhiJ7", "organisationUnits": [{"id": "O6uvpzGd5pu"}]},
    ]
}

_ATTRIBUTE_CATEGORY_COMBO = {
    "id": "O4VaNks6tta",
    "name": "Project",
    "isDefault": False,
    "categories": [{"id": "yY2bQYqNt0o", "categoryOptions": [{"id": "i4Nbp8S2G6A"}, {"id": "M58XdOfhiJ7"}]}],
    "categoryOptionCombos": [
        {"id": "XVl0bL5Bl4q", "name": "Improve access to clean water", "categoryOptions": [{"id": "i4Nbp8S2G6A"}]},
        {"id": "vp1qSLVMSc3", "name": "Provide access to basic education", "categoryOptions": [{"id": "M58XdOfhiJ7"}]},
    ],
}

#: The aggregate form, keyed by the restricted attribute combo and assigned to the whole registry.
_DATA_SETS_PAYLOAD = {
    "dataSets": [
        {
            "id": "lyLU2wR22tC",
            "name": "Project funding",
            "periodType": "Monthly",
            "organisationUnits": [{"id": "ImspTQPwCqd"}, {"id": "O6uvpzGd5pu"}],
            "categoryCombo": _ATTRIBUTE_CATEGORY_COMBO,
            "dataSetElements": [
                {
                    "dataElement": {
                        "id": "De1aaaaaaaa",
                        "name": "Households reached",
                        "valueType": "INTEGER_ZERO_OR_POSITIVE",
                        "domainType": "AGGREGATE",
                        "categoryCombo": {"id": "bjDvmb4bfuf", "name": "default", "isDefault": True},
                    }
                }
            ],
        }
    ]
}

#: The form whose DHIS2 assignment names an organisation unit this guide publishes none of.
#:
#: The assignment is a proper subset of the registry - it is disjoint from it - so the run publishes
#: an assignment List with no member at all, which is the third artifact shape this fixture is for.
_PROGRAMS_PAYLOAD = {
    "programs": [
        {
            "id": "VBqh0ynB2wv",
            "name": "Water point inspection",
            "programType": "WITHOUT_REGISTRATION",
            "organisationUnits": [{"id": "GvFqTavdpGE"}],
            "categoryCombo": {"id": "bjDvmb4bfuf", "name": "default", "isDefault": True},
            "programStages": [
                {
                    "id": "pTo4uMt3xur",
                    "name": "Inspection",
                    "programStageSections": [],
                    "programStageDataElements": [
                        {
                            "compulsory": True,
                            "dataElement": {"id": "qrur9Dvnyt5", "name": "Litres per day", "valueType": "INTEGER"},
                        }
                    ],
                }
            ],
        }
    ]
}

_OPTION_SETS_PAYLOAD: dict[str, Any] = {"optionSets": []}


def _mock_instance() -> None:
    """Mock every endpoint both builds read (respx-active)."""
    respx.get(f"{_HOST}/api/system/info").mock(return_value=httpx.Response(200, json=_SYSTEM_INFO))
    respx.get(f"{_HOST}/api/attributes").mock(return_value=httpx.Response(200, json={"attributes": []}))
    respx.get(f"{_HOST}/api/optionSets").mock(return_value=httpx.Response(200, json=_OPTION_SETS_PAYLOAD))
    respx.get(f"{_HOST}/api/categories").mock(return_value=httpx.Response(200, json=_CATEGORIES_PAYLOAD))
    respx.get(f"{_HOST}/api/categoryOptions").mock(return_value=httpx.Response(200, json=_CATEGORY_OPTIONS_PAYLOAD))
    respx.get(f"{_HOST}/api/dataSets").mock(return_value=httpx.Response(200, json=_DATA_SETS_PAYLOAD))
    respx.get(f"{_HOST}/api/programs").mock(return_value=httpx.Response(200, json=_PROGRAMS_PAYLOAD))
    respx.get(f"{_HOST}/api/programRules").mock(return_value=httpx.Response(200, json={"programRules": []}))
    respx.get(f"{_HOST}/api/organisationUnits").mock(return_value=httpx.Response(200, json=_ORGANISATION_UNITS_PAYLOAD))
    respx.get(f"{_HOST}/api/organisationUnitLevels").mock(
        return_value=httpx.Response(200, json=_ORGANISATION_UNIT_LEVELS_PAYLOAD)
    )


@pytest.fixture
def parity_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write a profiles.toml with a Basic `probe` profile both builds open a client on."""
    config_dir = tmp_path / ".config" / "dhis2"
    config_dir.mkdir(parents=True)
    (config_dir / "profiles.toml").write_text(_PROFILES_TOML, encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir.parent))
    monkeypatch.delenv("DHIS2_PROFILE", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def parity_project(tmp_path: Path) -> FhirProject:
    """The guide both stores are built for: a registry, a restricted attribute combo, one dead assignment."""
    config_path = tmp_path / "fhir.toml"
    config_path.write_text(_FHIR_TOML, encoding="utf-8")
    return FhirProject(config=load_fhir_config(config_path), config_path=config_path.resolve())


async def _live_store(project: FhirProject) -> ResourceStore:
    """Build the live store for the project against the mocked instance."""
    generation = resolve_generation_profile(project, None)
    settings = ServeSettings(project_dir=project.project_root, live=True)
    async with open_client(generation.profile) as client:
        return await build_live_store(project, settings, client)


async def _generate_to_disk(project: FhirProject) -> None:
    """Run every generate target over the same instance, writing the project's predefined tree."""
    generation = resolve_generation_profile(project, None)
    async with open_client(generation.profile) as client:
        await generate_full(generation.profile, project, client=client)


def _predefined_documents(project: FhirProject) -> dict[tuple[str, str], dict[str, Any]]:
    """Every resource a generate run committed under `ig/input/resources`, keyed as the store keys it."""
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(project.resources_directory.rglob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        documents[str(body["resourceType"]), str(body["id"])] = body
    return documents


def _live_documents(store: ResourceStore) -> dict[tuple[str, str], dict[str, Any]]:
    """Every document the live store serves, keyed the same way."""
    return {(entry.resource_type, entry.resource_id): entry.body for entry in store.entries}


@respx.mock
async def test_the_live_store_serves_every_artifact_a_generate_commits(
    parity_profile: None,  # noqa: ARG001
    parity_project: FhirProject,
) -> None:
    """The artifact sets agree: same resources, same ids, same bytes, in both directions where they can be."""
    _mock_instance()

    live = _live_documents(await _live_store(parity_project))
    await _generate_to_disk(parity_project)
    predefined = _predefined_documents(parity_project)

    assert predefined, "the generate run committed no predefined resource, so there is nothing to compare"
    missing = sorted(key for key in predefined if key not in live)
    assert missing == [], f"the live store publishes no {missing}, which a compiled store of the same guide does"
    for key, body in sorted(predefined.items()):
        assert live[key] == body, f"{key[0]}/{key[1]} is not the document a compiled store of the same guide serves"
    for resource_type in _PREDEFINED_ONLY_RESOURCE_TYPES:
        live_ids = sorted(key[1] for key in live if key[0] == resource_type)
        predefined_ids = sorted(key[1] for key in predefined if key[0] == resource_type)
        assert live_ids == predefined_ids, f"the two stores disagree about which {resource_type} the guide publishes"


@respx.mock
async def test_a_live_store_publishes_the_attribute_option_restrictions_it_read(
    parity_profile: None,  # noqa: ARG001
    parity_project: FhirProject,
) -> None:
    """The restriction Lists and the concept property naming them are served, so a capture can be graded.

    Without them the combo vocabulary reads as usable at every published organisation unit, and a
    draft generated against it is accepted here and refused by DHIS2 with `E8025`.
    """
    _mock_instance()

    live = _live_documents(await _live_store(parity_project))

    restrictions = {key[1]: body for key, body in live.items() if key[0] == "List" and key[1].startswith("d2-aoc-")}
    assert sorted(restrictions) == ["d2-aoc-M58XdOfhiJ7-org-units", "d2-aoc-i4Nbp8S2G6A-org-units"]
    narrowed = restrictions["d2-aoc-M58XdOfhiJ7-org-units"]
    assert [entry["item"]["reference"] for entry in narrowed["entry"]] == ["Location/O6uvpzGd5pu"]
    assert restrictions["d2-aoc-i4Nbp8S2G6A-org-units"].get("entry", []) == []
    code_system = live["CodeSystem", "d2-aoc-O4VaNks6tta-cs"]
    assert "dhis2-organisation-units" in {declared["code"] for declared in code_system["property"]}
    named = {
        concept["code"]: [
            item["valueString"] for item in concept["property"] if item["code"] == "dhis2-organisation-units"
        ]
        for concept in code_system["concept"]
    }
    assert named["XVl0bL5Bl4q"] == ["List/d2-aoc-i4Nbp8S2G6A-org-units"]
    assert named["vp1qSLVMSc3"] == ["List/d2-aoc-M58XdOfhiJ7-org-units"]
