"""What the attribute-combo vocabulary publishes about where a combo may be captured.

DHIS2 scopes a category option to organisation units, and a category option combo is usable at a
unit only where every option composing it is - so a data set assigned to the national root still
earns `E8025` for a value keyed to a combo whose options name only facilities. The vocabulary
publishes that scope the way the assignment target publishes a form's: one `List` of Locations per
restricted category option, named from every combo concept met from it.

Two economies are what make it publishable at national scale, and both are asserted here: the List
holds the published units the option admits rather than DHIS2's own restriction, so the descendant
rule is settled once at generate time; and an option that narrows nothing publishes nothing.
"""

from __future__ import annotations

import json
from typing import Any

from dhis2w_fhir.config import GenerateConfig
from dhis2w_fhir.names import StemResolution
from dhis2w_fhir.resources.attribute_combos import (
    ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
    AttributeComboBuild,
    AttributeOptionRestrictions,
    build_attribute_combo_artifacts,
)
from dhis2w_fhir.resources.attribute_combos.restrictions import (
    OrganisationUnitPaths,
    restricted_category_option_uids,
)
from dhis2w_fhir.resources.questionnaires.schemas import (
    CategoryComboIn,
    CategoryOptionComboIn,
    QuestionnaireSourceIn,
)

_CANONICAL = "http://example.org/fhir"

#: A three-level hierarchy, as DHIS2 states it: the root, one district under it, two facilities under that.
_ROOT = "ImspTQPwCqd"
_DISTRICT = "O6uvpzGd5pu"
_FACILITY = "DiszpKrYNg8"
_OTHER_FACILITY = "g8upMTyEZGZ"

_PATHS = OrganisationUnitPaths(
    paths={
        _ROOT: f"/{_ROOT}",
        _DISTRICT: f"/{_ROOT}/{_DISTRICT}",
        _FACILITY: f"/{_ROOT}/{_DISTRICT}/{_FACILITY}",
        _OTHER_FACILITY: f"/{_ROOT}/{_DISTRICT}/{_OTHER_FACILITY}",
    }
)

_PUBLISHED = StemResolution(stems={uid: uid for uid in _PATHS.paths})

#: The two category options the combo splits over: one partner, one project.
_PARTNER_OPTION = "LFsZ8v5v7rq"
_PROJECT_OPTION = "yMj2MnmNI8L"

#: The organisation unit an unrestricted option carries no List for, and the facility the project is run at.
_UNRESTRICTED: frozenset[str] = frozenset()

_ITEM_UID = "De1aaaaaaaa"

_COMBO = CategoryComboIn(
    uid="idcDPkDtepR",
    name="Implementing Partner and Projects",
    is_default=False,
    option_combos=[
        CategoryOptionComboIn(
            uid="BqblOcSwGey",
            name="Plan International, Primary health care",
            category_option_uids=[_PARTNER_OPTION, _PROJECT_OPTION],
        ),
        CategoryOptionComboIn(
            uid="oawMLLH7OjA",
            name="Plan International, Basic education",
            category_option_uids=[_PARTNER_OPTION],
        ),
    ],
)

_DEFAULT_COMBO = CategoryComboIn(uid="bjDvmb4bfuf", name="default", is_default=True)


def _source(attribute_combo: CategoryComboIn) -> QuestionnaireSourceIn:
    """One aggregate form on the given category combo."""
    return QuestionnaireSourceIn(
        uid="TuL8IOPzpHh",
        name="ART monthly summary",
        kind="aggregate",
        period_type="Monthly",
        attribute_combo=attribute_combo,
        flat_items=[],
    )


def _build(restriction: frozenset[str], *, published: StemResolution = _PUBLISHED) -> AttributeComboBuild:
    """Run the emitter with the project option restricted to `restriction`."""
    return build_attribute_combo_artifacts(
        [_source(_COMBO)],
        GenerateConfig(),
        _CANONICAL,
        ig_status="draft",
        restrictions=AttributeOptionRestrictions(
            organisation_units={_PROJECT_OPTION: restriction} if restriction else {},
            units=_PATHS,
            published=published,
        ),
    )


def _artifact(build: AttributeComboBuild, name: str) -> dict[str, Any]:
    """One emitted artifact parsed back out of the JSON the sync writes verbatim."""
    matched = [artifact for artifact in build.artifacts if artifact.relative_path.endswith(name)]
    assert len(matched) == 1, f"{name} not among {[artifact.relative_path for artifact in build.artifacts]}"
    parsed: dict[str, Any] = json.loads(matched[0].content)
    return parsed


def _restriction_properties(concept: dict[str, Any]) -> list[str]:
    """Every restriction List one concept names, in the order it names them."""
    return [
        concept_property["valueString"]
        for concept_property in concept.get("property") or []
        if concept_property["code"] == ATTRIBUTE_OPTION_RESTRICTION_PROPERTY
    ]


def _concepts(build: AttributeComboBuild) -> dict[str, dict[str, Any]]:
    """The emitted CodeSystem's concepts, by concept code."""
    code_system = _artifact(build, "CodeSystem-d2-aoc-idcDPkDtepR-cs.json")
    return {concept["code"]: concept for concept in code_system["concept"]}


def test_a_restricted_option_publishes_the_published_units_beneath_it() -> None:
    """DHIS2's rule is descendant-or-self, so a district restriction admits the facilities under it too."""
    build = _build(frozenset({_DISTRICT}))

    published = _artifact(build, f"List-d2-aoc-{_PROJECT_OPTION}-org-units.json")

    assert published["resourceType"] == "List"
    assert [entry["item"]["reference"] for entry in published["entry"]] == sorted(
        (f"Location/{_DISTRICT}", f"Location/{_FACILITY}", f"Location/{_OTHER_FACILITY}")
    )


def test_only_the_concepts_met_from_a_restricted_option_name_its_list() -> None:
    """The restriction is the option's, so the combos that are not met from it carry nothing."""
    build = _build(frozenset({_DISTRICT}))

    concepts = _concepts(build)

    assert _restriction_properties(concepts["BqblOcSwGey"]) == [f"List/d2-aoc-{_PROJECT_OPTION}-org-units"]
    assert _restriction_properties(concepts["oawMLLH7OjA"]) == []


def test_a_carried_restriction_is_declared_on_the_code_system() -> None:
    """A vocabulary states its own properties, so a reader needs nothing but the CodeSystem to follow one."""
    build = _build(frozenset({_DISTRICT}))

    code_system = _artifact(build, "CodeSystem-d2-aoc-idcDPkDtepR-cs.json")

    declared = [
        declaration
        for declaration in code_system["property"]
        if declaration["code"] == ATTRIBUTE_OPTION_RESTRICTION_PROPERTY
    ]

    assert len(declared) == 1
    assert declared[0]["type"] == "string"
    assert declared[0]["uri"].endswith(f"/property/{ATTRIBUTE_OPTION_RESTRICTION_PROPERTY}")


def test_an_option_the_whole_registry_sits_under_publishes_nothing() -> None:
    """A restriction every published unit already satisfies narrows nothing, and absence says exactly that."""
    build = _build(frozenset({_ROOT}))

    assert [artifact.relative_path for artifact in build.artifacts if "List-" in artifact.relative_path] == []
    assert _restriction_properties(_concepts(build)["BqblOcSwGey"]) == []


def test_an_option_no_published_unit_sits_under_publishes_an_empty_list() -> None:
    """The combo is usable nowhere here, which an empty List states and an absent one would not."""
    build = _build(frozenset({"Cannotbefound"}))

    published = _artifact(build, f"List-d2-aoc-{_PROJECT_OPTION}-org-units.json")

    assert "entry" not in published
    assert _restriction_properties(_concepts(build)["BqblOcSwGey"]) == [f"List/d2-aoc-{_PROJECT_OPTION}-org-units"]


def test_an_unrestricted_option_publishes_no_restriction() -> None:
    """An option DHIS2 assigns to no organisation unit is available everywhere, and states nothing."""
    build = _build(_UNRESTRICTED)

    assert [artifact.relative_path for artifact in build.artifacts if "List-" in artifact.relative_path] == []
    assert _restriction_properties(_concepts(build)["BqblOcSwGey"]) == []


def test_a_registry_mode_list_names_its_units_absolutely() -> None:
    """A relative reference does not resolve across a package dependency, so the registry's authority rides along."""
    registry = "http://example.org/fhir/registry"
    build = _build(
        frozenset({_FACILITY}),
        published=StemResolution(stems={uid: uid for uid in _PATHS.paths}, reference_base=f"{registry}/"),
    )

    published = _artifact(build, f"List-d2-aoc-{_PROJECT_OPTION}-org-units.json")

    assert [entry["item"]["reference"] for entry in published["entry"]] == [f"{registry}/Location/{_FACILITY}"]


def test_only_the_options_of_a_non_default_attribute_combo_are_read() -> None:
    """The restriction read is scoped to the vocabularies the run publishes, not to every option the instance holds."""
    assert restricted_category_option_uids([_source(_COMBO)]) == sorted({_PARTNER_OPTION, _PROJECT_OPTION})
    assert restricted_category_option_uids([_source(_DEFAULT_COMBO)]) == []
