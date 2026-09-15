"""What the attribute-combo vocabulary publishes about when a combo may be captured.

DHIS2 scopes a category option by calendar window as well as by organisation unit, and refuses a
data value set whose period the window does not cover with `E8032 Untimely data entry`. The
vocabulary publishes that window on the combo concept itself - `dhis2-valid-from` /
`dhis2-valid-to` - rather than as a resource of its own, because a window is two dates and a
restriction is thousands of organisation units.

The economy the unit axis takes as an intersection, this one takes as the narrowest window: a combo
is open only while every option it is met from is, which is the latest start and the earliest end.
That is DHIS2's own `CategoryOptionCombo` date range, and asserting it here is what keeps a draft
and the instance agreeing about which periods a combo takes.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from dhis2w_fhir.config import GenerateConfig
from dhis2w_fhir.names import StemResolution
from dhis2w_fhir.resources.attribute_combos import (
    AttributeComboBuild,
    AttributeOptionRestrictions,
    CategoryOptionValidity,
    build_attribute_combo_artifacts,
)
from dhis2w_fhir.resources.attribute_combos.restrictions import (
    ATTRIBUTE_OPTION_VALID_FROM_PROPERTY,
    ATTRIBUTE_OPTION_VALID_TO_PROPERTY,
    OrganisationUnitPaths,
)
from dhis2w_fhir.resources.questionnaires.schemas import (
    CategoryComboIn,
    CategoryOptionComboIn,
    QuestionnaireSourceIn,
)

_CANONICAL = "http://example.org/fhir"

_ROOT = "ImspTQPwCqd"
_PATHS = OrganisationUnitPaths(paths={_ROOT: f"/{_ROOT}"})
_PUBLISHED = StemResolution(stems={_ROOT: _ROOT})

#: The two category options the combo splits over: one partner, one project.
_PARTNER_OPTION = "LFsZ8v5v7rq"
_PROJECT_OPTION = "yMj2MnmNI8L"

#: The combo met from both, and the combo met from the partner alone.
_BOTH = "BqblOcSwGey"
_PARTNER_ONLY = "oawMLLH7OjA"

_COMBO = CategoryComboIn(
    uid="idcDPkDtepR",
    name="Implementing Partner and Projects",
    is_default=False,
    option_combos=[
        CategoryOptionComboIn(
            uid=_BOTH,
            name="Plan International, Primary health care",
            category_option_uids=[_PARTNER_OPTION, _PROJECT_OPTION],
        ),
        CategoryOptionComboIn(
            uid=_PARTNER_ONLY,
            name="Plan International, Basic education",
            category_option_uids=[_PARTNER_OPTION],
        ),
    ],
)


def _source() -> QuestionnaireSourceIn:
    """One aggregate form on the dated category combo."""
    return QuestionnaireSourceIn(
        uid="TuL8IOPzpHh",
        name="ART monthly summary",
        kind="aggregate",
        period_type="Monthly",
        attribute_combo=_COMBO,
        flat_items=[],
    )


def _build(validity: dict[str, CategoryOptionValidity]) -> AttributeComboBuild:
    """Run the emitter with the given windows on the category options."""
    return build_attribute_combo_artifacts(
        [_source()],
        GenerateConfig(),
        _CANONICAL,
        ig_status="draft",
        restrictions=AttributeOptionRestrictions(validity=validity, units=_PATHS, published=_PUBLISHED),
    )


def _code_system(build: AttributeComboBuild) -> dict[str, Any]:
    """The emitted attribute-combo CodeSystem, parsed back out of the JSON the sync writes verbatim."""
    matched = [
        artifact
        for artifact in build.artifacts
        if artifact.relative_path.endswith("CodeSystem-d2-aoc-idcDPkDtepR-cs.json")
    ]
    assert len(matched) == 1
    parsed: dict[str, Any] = json.loads(matched[0].content)
    return parsed


def _window(build: AttributeComboBuild, concept_code: str) -> dict[str, str]:
    """The two validity properties one concept carries, by property code."""
    concepts = {concept["code"]: concept for concept in _code_system(build)["concept"]}
    return {
        concept_property["code"]: concept_property["valueDateTime"]
        for concept_property in concepts[concept_code].get("property") or []
        if concept_property["code"] in (ATTRIBUTE_OPTION_VALID_FROM_PROPERTY, ATTRIBUTE_OPTION_VALID_TO_PROPERTY)
    }


def test_a_dated_option_states_its_window_on_every_concept_met_from_it() -> None:
    """The window is the option's, so the combos met from it carry it and the others carry nothing."""
    build = _build({_PROJECT_OPTION: CategoryOptionValidity(valid_to=datetime.date(2016, 10, 1))})

    assert _window(build, _BOTH) == {ATTRIBUTE_OPTION_VALID_TO_PROPERTY: "2016-10-01"}
    assert _window(build, _PARTNER_ONLY) == {}


def test_a_concept_met_from_two_dated_options_carries_the_narrowest_window() -> None:
    """A combo is open only while all its options are - the latest start, the earliest end."""
    build = _build(
        {
            _PARTNER_OPTION: CategoryOptionValidity(
                valid_from=datetime.date(2016, 4, 1), valid_to=datetime.date(2020, 1, 1)
            ),
            _PROJECT_OPTION: CategoryOptionValidity(
                valid_from=datetime.date(2015, 1, 1), valid_to=datetime.date(2016, 10, 1)
            ),
        }
    )

    assert _window(build, _BOTH) == {
        ATTRIBUTE_OPTION_VALID_FROM_PROPERTY: "2016-04-01",
        ATTRIBUTE_OPTION_VALID_TO_PROPERTY: "2016-10-01",
    }


def test_a_carried_window_is_declared_on_the_code_system() -> None:
    """A vocabulary states its own properties, so a reader needs nothing but the CodeSystem to follow one."""
    build = _build({_PROJECT_OPTION: CategoryOptionValidity(valid_from=datetime.date(2016, 4, 1))})

    declared = {
        declaration["code"]: declaration
        for declaration in _code_system(build)["property"]
        if declaration["code"] in (ATTRIBUTE_OPTION_VALID_FROM_PROPERTY, ATTRIBUTE_OPTION_VALID_TO_PROPERTY)
    }

    assert list(declared) == [ATTRIBUTE_OPTION_VALID_FROM_PROPERTY]
    assert declared[ATTRIBUTE_OPTION_VALID_FROM_PROPERTY]["type"] == "dateTime"
    assert declared[ATTRIBUTE_OPTION_VALID_FROM_PROPERTY]["uri"].endswith(
        f"/property/{ATTRIBUTE_OPTION_VALID_FROM_PROPERTY}"
    )


def test_an_option_stating_neither_date_publishes_nothing() -> None:
    """Absence means always open, which is what DHIS2 answers for an option carrying neither date."""
    build = _build({})

    assert _window(build, _BOTH) == {}
    assert [
        declaration["code"]
        for declaration in _code_system(build)["property"]
        if declaration["code"].startswith("dhis2-valid")
    ] == []


def test_the_window_covers_a_period_on_both_ends_inclusive() -> None:
    """DHIS2's own rule, read off 2.43 with validate-only posts against a category option ending 2016-10-01.

    Period `201609` is accepted and `201610` refused although that period begins on the very day the
    option closes, so the whole period has to sit inside the window and equality passes.
    """
    window = CategoryOptionValidity(valid_from=datetime.date(2016, 4, 1), valid_to=datetime.date(2016, 10, 1))

    assert window.covers(datetime.date(2016, 9, 1), datetime.date(2016, 9, 30))
    assert not window.covers(datetime.date(2016, 10, 1), datetime.date(2016, 10, 31))
    assert window.covers(datetime.date(2016, 4, 1), datetime.date(2016, 4, 30))
    assert not window.covers(datetime.date(2016, 3, 1), datetime.date(2016, 3, 31))


def test_an_open_ended_window_covers_everything_beyond_it() -> None:
    """Either end absent is DHIS2 saying the combo was always open, or is never closed."""
    assert CategoryOptionValidity(valid_to=datetime.date(2016, 10, 1)).covers(
        datetime.date(1970, 1, 1), datetime.date(1970, 1, 31)
    )
    assert CategoryOptionValidity(valid_from=datetime.date(2016, 4, 1)).covers(
        datetime.date(2099, 1, 1), datetime.date(2099, 1, 31)
    )
    assert CategoryOptionValidity().covers(datetime.date(2016, 10, 1), datetime.date(2016, 10, 31))
