"""Where a published example reports from, which attribute option combo it is keyed to, and for when.

DHIS2 grades all three together. It refuses a capture outside the form's organisation-unit
assignment (`E1029`), one keyed to an attribute option combo whose category options are scoped away
from the organisation unit it was filed from (`E8025`), and one whose combo window does not cover
the whole period it reports for (`E8032`). A guide's own example is the shape a consumer copies and
the first thing anybody POSTs, so it is placed the way a capture has to be: the unit, the combo and
the period drawn as one choice, out of the triples the instance would take.

The form no triple exists for is the other half of the same rule. It is dead at generate time - no
capture for it can be keyed to anything DHIS2 accepts - and the run says so out loud rather than
publishing an example the facade then refuses.
"""

from __future__ import annotations

import datetime

from dhis2w_fhir.config import GenerateConfig
from dhis2w_fhir.names import StemResolution
from dhis2w_fhir.resources.attribute_combos.restrictions import (
    AttributeOptionRestrictions,
    CategoryOptionValidity,
    OrganisationUnitPaths,
    UsableAttributeOptionCombos,
)
from dhis2w_fhir.resources.examples import build_synthetic_responses
from dhis2w_fhir.resources.questionnaires.assignments import AssignmentIndex
from dhis2w_fhir.resources.questionnaires.schemas import (
    CategoryComboIn,
    CategoryOptionComboIn,
    QuestionnaireSourceIn,
)
from dhis2w_fhir.service import (
    _plan_example_placements,
    _untimely_attribute_option_combos,
    _unusable_attribute_option_combos,
)

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

_PUBLISHED = StemResolution(stems=dict.fromkeys(_PATHS.paths, ""))
_PUBLISHED_UIDS = frozenset(_PATHS.paths)

#: The two category options the combo splits over, one of which DHIS2 scopes to organisation units.
_PARTNER_OPTION = "LFsZ8v5v7rq"
_PROJECT_OPTION = "yMj2MnmNI8L"

#: The form's own UID, and the two combos it may key a capture under.
_FORM = "TuL8IOPzpHh"
_LEAF_COMBO = "BqblOcSwGey"
_OTHER_LEAF_COMBO = "oawMLLH7OjA"

_COMBO = CategoryComboIn(
    uid="idcDPkDtepR",
    name="Implementing Partner and Projects",
    is_default=False,
    option_combos=[
        CategoryOptionComboIn(
            uid=_LEAF_COMBO,
            name="Plan International, Primary health care",
            category_option_uids=[_PARTNER_OPTION, _PROJECT_OPTION],
        ),
        CategoryOptionComboIn(
            uid=_OTHER_LEAF_COMBO,
            name="Plan International, Basic education",
            category_option_uids=[_PROJECT_OPTION],
        ),
    ],
)

_TODAY = datetime.date(2026, 3, 14)

#: A window that opened years before any period this form still reports, which refuses nothing.
_OPENED = datetime.date(2016, 4, 1)


def _source() -> QuestionnaireSourceIn:
    """The one aggregate form these tests place, on a non-default category combo."""
    return QuestionnaireSourceIn(
        uid=_FORM,
        name="ART monthly summary",
        kind="aggregate",
        period_type="Monthly",
        attribute_combo=_COMBO,
        flat_items=[],
    )


def _restrictions(
    restricted_to: frozenset[str], validity: dict[str, CategoryOptionValidity] | None = None
) -> AttributeOptionRestrictions:
    """The run's restriction index with the project category option scoped to `restricted_to`, and windows."""
    return AttributeOptionRestrictions(
        organisation_units={_PROJECT_OPTION: restricted_to} if restricted_to else {},
        validity=validity or {},
        units=_PATHS,
        published=_PUBLISHED,
    )


def _assignment(units: frozenset[str]) -> AssignmentIndex:
    """The form assigned to exactly these organisation units."""
    return AssignmentIndex(organisation_units={_FORM: units})


def _plan(
    assigned: frozenset[str],
    restricted_to: frozenset[str],
    validity: dict[str, CategoryOptionValidity] | None = None,
) -> object:
    """Plan the one form's example placement under one assignment, one restriction, and one set of windows."""
    return _plan_example_placements(
        [_source()],
        _assignment(assigned),
        _PUBLISHED_UIDS,
        _ROOT,
        UsableAttributeOptionCombos.of(_restrictions(restricted_to, validity)),
        _TODAY,
    )


def test_the_example_is_placed_where_its_combo_is_usable_rather_than_at_the_root() -> None:
    """The root is assigned and publishes a Location, and the combo is still refused there - so it is not used."""
    plan = _plan(frozenset({_ROOT, _FACILITY}), frozenset({_FACILITY}))

    placement = plan.placements[_FORM]  # type: ignore[attr-defined]

    assert placement.organisation_unit_uids == (_FACILITY,)
    assert placement.usable_attribute_option_combo_uids == {_FACILITY: (_LEAF_COMBO, _OTHER_LEAF_COMBO)}


def test_only_the_combos_the_placed_unit_admits_are_offered_to_the_draw() -> None:
    """One option restricted away and one not is a unit that admits some combos and refuses others."""
    combos = UsableAttributeOptionCombos.of(_restrictions(frozenset({_OTHER_FACILITY})))

    assert combos.usable_at(_source(), _OTHER_FACILITY, period=None) == (_LEAF_COMBO, _OTHER_LEAF_COMBO)
    assert combos.usable_at(_source(), _FACILITY, period=None) == ()


def test_every_generated_example_is_keyed_to_a_combo_its_own_unit_admits() -> None:
    """The draw ranges over the pairs DHIS2 takes, so no ordinal of the run produces an E8025."""
    plan = _plan(frozenset({_ROOT, _FACILITY}), frozenset({_FACILITY}))

    build = build_synthetic_responses(
        [_source()],
        [],
        6,
        _ROOT,
        _TODAY,
        placements=plan.placements,  # type: ignore[attr-defined]
    )

    assert build.responses
    for response in build.responses:
        assert response.organisation_unit_uid == _FACILITY
        assert response.attribute_option_combo_uid in {_LEAF_COMBO, _OTHER_LEAF_COMBO}


def test_a_form_no_admitted_unit_may_file_any_combo_at_publishes_no_example() -> None:
    """There is no capture DHIS2 would take, so the run drafts none rather than one it refuses."""
    plan = _plan(frozenset({_ROOT}), frozenset({_FACILITY}))

    assert plan.sources == []  # type: ignore[attr-defined]
    assert plan.placements == {}  # type: ignore[attr-defined]
    assert any("restricts away" in note.message for note in plan.notes)  # type: ignore[attr-defined]


def test_the_form_no_organisation_unit_may_file_a_capture_for_is_summarised_for_the_terminal() -> None:
    """The run knows at generate time, so it closes with the fact rather than leaving it to the facade's 422."""
    summary = _unusable_attribute_option_combos(
        [_source()],
        _assignment(frozenset({_ROOT})),
        _restrictions(frozenset({_FACILITY})),
        GenerateConfig(),
        _PUBLISHED,
    )

    assert summary is not None
    assert summary.form_count == 1
    assert summary.forms == [f"ART monthly summary ({_FORM})"]


def test_a_form_with_one_usable_pair_is_not_summarised() -> None:
    """One organisation unit admitting one combo is a form somebody may submit, and nothing is said."""
    summary = _unusable_attribute_option_combos(
        [_source()],
        _assignment(frozenset({_ROOT, _FACILITY})),
        _restrictions(frozenset({_FACILITY})),
        GenerateConfig(),
        _PUBLISHED,
    )

    assert summary is None


def test_a_form_assigned_nowhere_is_left_to_the_assignment_summary() -> None:
    """One loss reported under two names would be two losses, so the empty assignment owns that form."""
    summary = _unusable_attribute_option_combos(
        [_source()],
        _assignment(frozenset()),
        _restrictions(frozenset({_FACILITY})),
        GenerateConfig(),
        _PUBLISHED,
    )

    assert summary is None


def test_a_run_resolving_no_restriction_draws_from_the_whole_vocabulary() -> None:
    """An instance restricting nothing admits every combo everywhere, and the placement says so by holding none."""
    plan = _plan(frozenset({_ROOT}), frozenset())

    placement = plan.placements[_FORM]  # type: ignore[attr-defined]

    assert placement.organisation_unit_uids == (_ROOT,)
    assert placement.usable_attribute_option_combo_uids == {_ROOT: (_LEAF_COMBO, _OTHER_LEAF_COMBO)}


#: A window that closed years before any period this form still reports, which is what DHIS2 answers `E8032` for.
_CLOSED = CategoryOptionValidity(valid_to=datetime.date(2016, 10, 1))


def test_the_example_is_keyed_to_a_combo_still_open_for_the_period_it_reports() -> None:
    """One combo of the two closed before the reported period, so the draw is left the one DHIS2 still takes."""
    plan = _plan(frozenset({_ROOT}), frozenset(), {_PARTNER_OPTION: _CLOSED})

    placement = plan.placements[_FORM]  # type: ignore[attr-defined]

    assert placement.usable_attribute_option_combo_uids == {_ROOT: (_OTHER_LEAF_COMBO,)}


def test_every_generated_example_is_keyed_to_a_combo_open_for_its_own_period() -> None:
    """The draw ranges over the open combos alone, so no ordinal of the run produces an E8032."""
    plan = _plan(frozenset({_ROOT}), frozenset(), {_PARTNER_OPTION: _CLOSED})

    build = build_synthetic_responses(
        [_source()],
        [],
        6,
        _ROOT,
        _TODAY,
        placements=plan.placements,  # type: ignore[attr-defined]
    )

    assert build.responses
    for response in build.responses:
        assert response.attribute_option_combo_uid == _OTHER_LEAF_COMBO


def test_a_form_whose_every_combo_has_closed_publishes_no_example() -> None:
    """The date axis loses the form exactly as the unit axis does, and says so in the same aggregate note."""
    plan = _plan(frozenset({_ROOT}), frozenset(), {_PROJECT_OPTION: _CLOSED})

    assert plan.sources == []  # type: ignore[attr-defined]
    assert plan.placements == {}  # type: ignore[attr-defined]
    notes = plan.notes  # type: ignore[attr-defined]
    assert any("has closed for the period they report" in note.message for note in notes)


def test_a_combo_open_for_the_reported_period_is_left_alone() -> None:
    """A window covering the period the example reports for narrows nothing, which is the common case."""
    plan = _plan(frozenset({_ROOT}), frozenset(), {_PROJECT_OPTION: CategoryOptionValidity(valid_from=_OPENED)})

    placement = plan.placements[_FORM]  # type: ignore[attr-defined]

    assert placement.usable_attribute_option_combo_uids == {_ROOT: (_LEAF_COMBO, _OTHER_LEAF_COMBO)}


def test_the_form_every_combo_of_which_has_closed_is_summarised_for_the_terminal() -> None:
    """The run knows at generate time, so it closes with the fact rather than leaving it to the facade's 422."""
    restrictions = _restrictions(frozenset(), {_PROJECT_OPTION: _CLOSED})

    summary = _untimely_attribute_option_combos([_source()], restrictions, _TODAY)

    assert summary is not None
    assert summary.form_count == 1
    assert summary.forms == [f"ART monthly summary ({_FORM})"]


def test_a_form_with_one_open_combo_is_not_summarised_on_the_date_axis() -> None:
    """One combo DHIS2 still takes is a form somebody may submit, and nothing is said."""
    restrictions = _restrictions(frozenset(), {_PARTNER_OPTION: _CLOSED})

    assert _untimely_attribute_option_combos([_source()], restrictions, _TODAY) is None


def test_a_form_reporting_for_no_period_is_left_off_the_date_axis() -> None:
    """An event program's capture reports for no period, so a closed window has nothing to refuse it by."""
    event = _source().model_copy(update={"kind": "event", "period_type": None})
    restrictions = _restrictions(frozenset(), {_PROJECT_OPTION: _CLOSED})

    assert _untimely_attribute_option_combos([event], restrictions, _TODAY) is None
