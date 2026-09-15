"""Where and when an attribute option combo may be captured, published beside the vocabulary itself.

DHIS2 scopes a category option two ways, and a combo is usable only where every option composing it
is on both: to organisation units, published here as one `List` per restricted option, and to a
calendar window, published here as a pair of concept properties on the combo concept.

DHIS2 scopes a category option to organisation units: `CategoryOption.organisationUnits` names the
units the option is available at, and an option naming none is available everywhere. A category
option combo is met from one option per category axis, so the combo is usable at a unit exactly
when every option composing it is - `CategoryOptionCombo.isAssignedToOrganisationUnit` is the
conjunction, and each option admits the units it names **and everything beneath them**, which is
why a data set assigned to the national root still refuses a value keyed to a combo whose options
name only facilities (`E8025 Attribute option combo ... not usable with org unit(s)`).

The publication is the assignment family's, because the fact has the assignment's shape: one `List`
of Locations per restricted category option, and a concept property on every combo concept met from
that option naming the List. A combo concept therefore states, on the vocabulary itself, every
restriction its options carry, and a client honours them by admitting only the units on all of them.

Two economies keep it publishable at national scale:

- **A List names published units rather than DHIS2's own restriction.** The members are the units
  of this run's registry selection that sit at or under one of the restricted units, resolved off
  DHIS2's own `path`, so the ancestor rule is settled once here and a reader tests plain membership.
- **A List is written only where the option narrows the registry.** An option restricted to
  something every published unit already sits under narrows nothing, publishes nothing, and its
  concepts carry no property - absence means the whole registry, which is what a consumer assumed.
  An option no published unit sits under publishes an empty List: the combo is usable nowhere here.

THE DATE AXIS. `CategoryOption.startDate` and `CategoryOption.endDate` open the option for a
calendar window, and DHIS2 refuses a data value set whose period falls outside the window of any
option behind its attribute option combo with `E8032 Untimely data entry`. The window is two dates
rather than a set of thousands, so it rides the concept itself as `dhis2-valid-from` /
`dhis2-valid-to` rather than a resource of its own, and what a concept carries is the **narrowest**
window of the options it is met from - the latest start and the earliest end - because a combo is
open only while all of them are. That is the same conjunction the unit axis takes as an
intersection, and it is DHIS2's own `CategoryOptionCombo` date range. An option stating neither date
narrows nothing and publishes nothing: absence means always open, which is what a consumer assumed.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from dhis2w_fhir.names import StemResolution
from dhis2w_fhir.r4 import CodeSystemConceptProperty, CodeSystemProperty, ListEntry, Reference, ResourceList
from dhis2w_fhir.resources.attribute_combos.schemas import ATTRIBUTE_COMBO_DIRECTORY
from dhis2w_fhir.writer import JsonArtifact, JsonBuild

if TYPE_CHECKING:
    from collections.abc import Collection

    from dhis2w_fhir.period.schemas import PeriodValue
    from dhis2w_fhir.resources.questionnaires.schemas import QuestionnaireSourceIn

__all__ = [
    "ATTRIBUTE_OPTION_RESTRICTION_ID_SUFFIX",
    "ATTRIBUTE_OPTION_RESTRICTION_PROPERTY",
    "ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE",
    "ATTRIBUTE_OPTION_VALID_FROM_PROPERTY",
    "ATTRIBUTE_OPTION_VALID_TO_PROPERTY",
    "UNTIMELY_ATTRIBUTE_OPTION_COMBO_REMEDY",
    "UNUSABLE_ATTRIBUTE_OPTION_COMBO_REMEDY",
    "AttributeOptionRestrictionBuild",
    "AttributeOptionRestrictionPlan",
    "AttributeOptionRestrictions",
    "CategoryOptionValidity",
    "OrganisationUnitPaths",
    "UntimelyAttributeOptionCombosSummary",
    "UnusableAttributeOptionCombosSummary",
    "UsableAttributeOptionCombos",
    "attribute_option_restriction_declaration",
    "attribute_option_validity_declarations",
    "build_attribute_option_restriction_artifacts",
    "narrowest_window",
    "restricted_category_option_uids",
    "untimely_attribute_option_combo_message",
    "untimely_attribute_option_combos_summary",
    "unusable_attribute_option_combo_message",
    "unusable_attribute_option_combos_summary",
]

#: The concept property naming one restriction List, repeated once per restricted option of the combo.
ATTRIBUTE_OPTION_RESTRICTION_PROPERTY = "dhis2-organisation-units"

#: The concept properties stating the calendar window every category option of the combo is open for.
ATTRIBUTE_OPTION_VALID_FROM_PROPERTY = "dhis2-valid-from"
ATTRIBUTE_OPTION_VALID_TO_PROPERTY = "dhis2-valid-to"

#: The resource type a restriction is published as, and the prefix of the reference a property carries.
ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE = "List"

#: The trailing token every restriction List id ends in, after the attribute-combo stem and the option UID.
ATTRIBUTE_OPTION_RESTRICTION_ID_SUFFIX = "org-units"

#: What the restriction property is called on the CodeSystem-level declaration every carrier emits.
_DECLARATION_DESCRIPTION = (
    "List of the organisation units a category option of this combo is restricted to. A capture is "
    "refused unless its organisation unit is on every List the concept names."
)

#: What the two validity properties are called on the CodeSystem-level declaration a carrier emits.
_VALID_FROM_DECLARATION_DESCRIPTION = (
    "First day this combo is open for. A capture is refused unless the whole period it reports for "
    "falls on or after it."
)
_VALID_TO_DECLARATION_DESCRIPTION = (
    "Last day this combo is open for. A capture is refused unless the whole period it reports for "
    "falls on or before it."
)


class OrganisationUnitPaths(BaseModel):
    """Where every organisation unit the registry selection publishes sits, as DHIS2's own `path` states it."""

    model_config = ConfigDict(frozen=True)

    paths: dict[str, str] = Field(default_factory=dict)
    """The DHIS2 `path` of each published unit, keyed by its UID - `/root/district/chiefdom/facility`."""

    def published_uids(self) -> frozenset[str]:
        """Every organisation unit UID the registry selection publishes."""
        return frozenset(self.paths)

    def under(self, restriction: Collection[str]) -> frozenset[str]:
        """Every published unit at or under one of these units - DHIS2's own rule for a restricted option.

        A `path` names the unit itself last and every ancestor before it, so a unit is admitted when
        the restriction names any segment of its own path. That is what `OrganisationUnit.isDescendant`
        decides on the instance, and deciding it here is what lets a published List be tested by
        membership alone.
        """
        restricted = set(restriction)
        return frozenset(uid for uid, path in self.paths.items() if restricted & set(path.strip("/").split("/")))


class CategoryOptionValidity(BaseModel):
    """The calendar window one attribute category option is open for, either end of it open.

    THE RULE, READ OFF DHIS2 2.43 ITSELF. A capture is refused with `E8032 Untimely data entry`
    unless the window covers the **whole** period it reports for, both ends inclusive: the start has
    to fall on or before the period's first day, the end on or after its last. Confirmed by
    validate-only posts against a category option ending `2016-10-01` - period `201609` accepted,
    `201610` refused although that period begins on the very day the option ends - and against one
    starting `2016-04-01` - `201603` refused, `201604` accepted on the equality.
    """

    model_config = ConfigDict(frozen=True)

    valid_from: datetime.date | None = None
    """The option's `startDate`, as a calendar day - None where DHIS2 opens it from the beginning."""

    valid_to: datetime.date | None = None
    """The option's `endDate`, as a calendar day - None where DHIS2 leaves it open-ended."""

    @property
    def stated(self) -> bool:
        """Whether the option narrows anything at all, which is what decides if a concept carries the pair."""
        return self.valid_from is not None or self.valid_to is not None

    def narrowed_by(self, other: CategoryOptionValidity) -> CategoryOptionValidity:
        """The window both options are open for - the later start and the earlier end, which is DHIS2's own rule."""
        return CategoryOptionValidity(
            valid_from=_later(self.valid_from, other.valid_from),
            valid_to=_earlier(self.valid_to, other.valid_to),
        )

    def covers(self, start_date: datetime.date, end_date: datetime.date) -> bool:
        """Whether a capture reporting for this span falls inside the window, both ends inclusive."""
        return not self.opens_after(start_date) and not self.closed_before(end_date)

    def opens_after(self, start_date: datetime.date) -> bool:
        """Whether the window opens later than this day, which is what refuses a capture beginning before it."""
        return self.valid_from is not None and self.valid_from > start_date

    def closed_before(self, end_date: datetime.date) -> bool:
        """Whether the window closed earlier than this day, which is what refuses a capture running past it."""
        return self.valid_to is not None and self.valid_to < end_date


class AttributeOptionRestrictions(BaseModel):
    """What DHIS2 restricts each attribute category option to, and the registry a restriction is published against."""

    model_config = ConfigDict(frozen=True)

    organisation_units: dict[str, frozenset[str]] = Field(default_factory=dict)
    """The organisation units each attribute category option is restricted to, by category option UID.

    An option absent from the index carries no restriction, which is what DHIS2 answers for an
    option assigned to no organisation unit: every unit may capture under it.
    """

    validity: dict[str, CategoryOptionValidity] = Field(default_factory=dict)
    """The calendar window each attribute category option is open for, by category option UID.

    An option absent from the index states neither date, which is what DHIS2 answers for an option
    open from the beginning and never closed: a capture for any period may be keyed under it.
    """

    units: OrganisationUnitPaths = Field(default_factory=OrganisationUnitPaths)
    """Where the published organisation units sit, which is what resolves the restriction's descendants."""

    published: StemResolution = Field(default_factory=StemResolution)
    """The registry selection: the ids a List names its members by, relative or absolute into a package."""


#: The one line answering a form no organisation unit may file a capture for, stated identically wherever
#: the fact is reported - `d2w fhir generate` closes a run with it and `d2w fhir check-artifacts` files it
#: as a finding's remedy. Two selections meet here and the sentence names both: the organisation-unit
#: selection is the one to widen until a restricted unit is published, the form selection the one to narrow.
UNUSABLE_ATTRIBUTE_OPTION_COMBO_REMEDY = (
    "Widen the organisation-unit selection until one of the restricted organisation units is published - "
    "raise `[generate.organisation_units] max_level`, or set its `root` to an organisation unit above "
    "them - or narrow the form selection in fhir.toml to the forms those organisation units report, then "
    "run `d2w fhir generate` again."
)


#: The one line answering a form whose every attribute option combo has closed, stated identically wherever
#: the fact is reported - `d2w fhir generate` closes a run with it and `d2w fhir check-artifacts` files it as a
#: finding's remedy. Unlike the unit axis, no fhir.toml setting reaches this one: the window is DHIS2 metadata.
UNTIMELY_ATTRIBUTE_OPTION_COMBO_REMEDY = (
    "A category option's window is DHIS2 metadata - `startDate` and `endDate` on the category option - and "
    "fhir.toml has no setting that widens it. Reopen the category options in DHIS2, or narrow the form "
    "selection in fhir.toml to the forms whose attribute option combos are still open, then run "
    "`d2w fhir generate` again."
)


class UsableAttributeOptionCombos(BaseModel):
    """Which attribute option combos a capture at each published organisation unit, for a period, may be filed under.

    The restriction index read the way both consumers of it ask, and on both axes DHIS2 grades: it
    refuses a capture keyed to a combo whose category options are scoped away from the organisation
    unit it was filed from (`E8025`), and one whose window does not cover the whole period it reports
    for (`E8032`). So the examples target places a response and the questionnaires target grades a
    form against the same question - which combos, at which unit, for which period. The ancestor rule
    is resolved once per category option here rather than per combo per unit, because a national
    registry has thousands of units and a category combo has dozens of combos met from a handful of
    options.
    """

    model_config = ConfigDict(frozen=True)

    admissions: dict[str, frozenset[str]] = Field(default_factory=dict)
    """The published organisation units each restricted category option admits, by category option UID.

    An option absent from the index restricts nothing, which is what DHIS2 answers for an option
    assigned to no organisation unit: every published unit may capture under it.
    """

    validity: dict[str, CategoryOptionValidity] = Field(default_factory=dict)
    """The calendar window each dated category option is open for, by category option UID.

    An option absent from the index states neither date, which is what DHIS2 answers for an option
    open from the beginning and never closed: a capture for any period may be keyed under it.
    """

    @classmethod
    def of(cls, restrictions: AttributeOptionRestrictions) -> UsableAttributeOptionCombos:
        """Resolve every restricted category option's descendants against the published registry, once."""
        return cls(
            admissions={
                option_uid: restrictions.units.under(restricted_to)
                for option_uid, restricted_to in restrictions.organisation_units.items()
                if restricted_to
            },
            validity=dict(restrictions.validity),
        )

    def usable_at(
        self, source: QuestionnaireSourceIn, organisation_unit_uid: str, *, period: PeriodValue | None
    ) -> tuple[str, ...]:
        """The option combos of this form's category combo a capture here, for this period, may be filed under.

        Both axes at once, because DHIS2 grades both: a combo scoped away from the organisation unit
        is refused with `E8025`, and one whose window does not cover the whole period the capture
        reports for with `E8032`. `period` None is a capture reporting for no period at all - an
        event, an enrollment - which leaves the date axis nothing to grade and the unit axis alone.

        A form on the default category combo, or on one the run publishes no vocabulary for, declares
        no combo at all and the answer is empty - such a capture carries no combo and DHIS2 keys it
        under the default one.
        """
        combo = source.attribute_combo
        if combo is None or combo.is_default:
            return ()
        return tuple(
            option_combo.uid
            for option_combo in combo.option_combos
            if self.admits(organisation_unit_uid, option_combo.category_option_uids)
            and self.covers(option_combo.category_option_uids, period)
        )

    def admits(self, organisation_unit_uid: str, category_option_uids: Collection[str]) -> bool:
        """Whether a capture at this organisation unit may be filed under a combo met from these category options."""
        return all(
            organisation_unit_uid in admitted
            for option_uid in category_option_uids
            if (admitted := self.admissions.get(option_uid)) is not None
        )

    def covers(self, category_option_uids: Collection[str], period: PeriodValue | None) -> bool:
        """Whether a capture reporting for this period may be filed under a combo met from these category options."""
        if period is None:
            return True
        return self.window_of(category_option_uids).covers(period.start_date, period.end_date)

    def window_of(self, category_option_uids: Collection[str]) -> CategoryOptionValidity:
        """The window a combo met from these category options is open for - the narrowest of theirs."""
        return narrowest_window(self.validity, category_option_uids)


class UnusableAttributeOptionCombosSummary(BaseModel):
    """The published forms no organisation unit may file a capture for: every combo is restricted away.

    Counted in forms for the reason the empty-assignment summary is: the form is what a capture
    client is refused at, and what `$generate` answers 422 for. A form lands here only when it has
    somewhere to report from at all - a form assigned to no published organisation unit is the
    other absence, reported by the assignment summary, and reporting it twice would say one loss
    under two names.
    """

    model_config = ConfigDict(frozen=True)

    form_count: int
    """How many published Questionnaires declare a combo vocabulary no organisation unit may draw from."""

    forms: list[str]
    """The forms themselves, as `name (uid)`, sorted."""

    max_level: int | None = None
    """The `[generate.organisation_units] max_level` in force, which is what usually narrows the registry."""


class UntimelyAttributeOptionCombosSummary(BaseModel):
    """The published forms every attribute option combo of theirs has closed for: no period they report is inside one.

    The date axis's own answer to the unit axis's `UnusableAttributeOptionCombosSummary`, counted in
    forms for the same reason: the form is what a capture client is refused at, and what `$generate`
    answers 422 for. A form lands here only when every combo it declares closed before the end of the
    period it reports now, which is the first of the periods it still reports - DHIS2 refuses a
    capture the window does not cover entirely, and a window that ends before this period ends is
    before every later one too.
    """

    model_config = ConfigDict(frozen=True)

    form_count: int
    """How many published Questionnaires declare a combo vocabulary closed for every period they report."""

    forms: list[str]
    """The forms themselves, as `name (uid)`, sorted."""


class AttributeOptionRestrictionPlan(BaseModel):
    """Where and when each attribute option combo concept may be captured, keyed by the option combo's UID."""

    model_config = ConfigDict(frozen=True)

    list_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    """The restriction Lists each combo concept names, one per restricted option it is met from."""

    windows: dict[str, CategoryOptionValidity] = Field(default_factory=dict)
    """The narrowest calendar window each combo concept is open for - absent where every option is always open."""

    def properties_for(self, member_uid: str) -> list[CodeSystemConceptProperty]:
        """The restriction properties one attribute option combo concept carries: the units, then the window."""
        properties = [
            CodeSystemConceptProperty(
                code=ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
                valueString=f"{ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE}/{list_id}",
            )
            for list_id in self.list_ids.get(member_uid, ())
        ]
        window = self.windows.get(member_uid)
        if window is None:
            return properties
        if window.valid_from is not None:
            properties.append(
                CodeSystemConceptProperty(
                    code=ATTRIBUTE_OPTION_VALID_FROM_PROPERTY, valueDateTime=window.valid_from.isoformat()
                )
            )
        if window.valid_to is not None:
            properties.append(
                CodeSystemConceptProperty(
                    code=ATTRIBUTE_OPTION_VALID_TO_PROPERTY, valueDateTime=window.valid_to.isoformat()
                )
            )
        return properties


class AttributeOptionRestrictionBuild(JsonBuild):
    """The restriction Lists one run publishes, plus the plan the combo concepts name them by."""

    plan: AttributeOptionRestrictionPlan = Field(default_factory=AttributeOptionRestrictionPlan)


def unusable_attribute_option_combos_summary(
    forms: list[str], *, max_level: int | None
) -> UnusableAttributeOptionCombosSummary | None:
    """Summarise the forms no organisation unit may file a capture for, or None when every form has one."""
    if not forms:
        return None
    return UnusableAttributeOptionCombosSummary(form_count=len(forms), forms=sorted(forms), max_level=max_level)


def unusable_attribute_option_combo_message(summary: UnusableAttributeOptionCombosSummary) -> str:
    """The note one run files about the forms no organisation unit may file a capture for."""
    narrowed = (
        f"; `[generate.organisation_units] max_level = {summary.max_level}` is what narrows the registry"
        if summary.max_level is not None
        else ""
    )
    return (
        f"{summary.form_count} published form(s) declare attribute option combos DHIS2 restricts away from "
        f"every organisation unit that may report them, so no capture for them can be keyed to a combo this "
        f"DHIS2 instance accepts and the restriction Lists beside their vocabulary name no organisation unit "
        f"that may report them{narrowed}. The forms are: {', '.join(summary.forms)}"
    )


def untimely_attribute_option_combos_summary(forms: list[str]) -> UntimelyAttributeOptionCombosSummary | None:
    """Summarise the forms every attribute option combo of theirs has closed for, or None when none has."""
    if not forms:
        return None
    return UntimelyAttributeOptionCombosSummary(form_count=len(forms), forms=sorted(forms))


def untimely_attribute_option_combo_message(summary: UntimelyAttributeOptionCombosSummary) -> str:
    """The note one run files about the forms every attribute option combo of theirs has closed for."""
    return (
        f"{summary.form_count} published form(s) declare attribute option combos DHIS2 has closed: no attribute "
        f"option combo of the form is valid for any period it reports, so no capture for them can be keyed to a "
        f"combo this DHIS2 instance accepts. The forms are: {', '.join(summary.forms)}"
    )


def narrowest_window(
    validity: dict[str, CategoryOptionValidity], category_option_uids: Collection[str]
) -> CategoryOptionValidity:
    """The window a combo met from these category options is open for - the latest start, the earliest end.

    DHIS2's own `CategoryOptionCombo` date range, and the one rule every consumer of the date axis
    reads: the vocabulary emitter narrows a concept's published window by it, the examples target
    keys a response by it, and `d2w fhir check-artifacts` reads it back off the published properties.
    An option stating neither date narrows nothing, so a combo met from such options alone is open
    for every period there is.
    """
    window = CategoryOptionValidity()
    for option_uid in category_option_uids:
        stated = validity.get(option_uid)
        if stated is not None:
            window = window.narrowed_by(stated)
    return window


def attribute_option_restriction_declaration(property_base: str) -> CodeSystemProperty:
    """The CodeSystem-level declaration every vocabulary carrying a restriction emits."""
    return CodeSystemProperty(
        code=ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
        uri=f"{property_base}/{ATTRIBUTE_OPTION_RESTRICTION_PROPERTY}",
        description=_DECLARATION_DESCRIPTION,
        type="string",
    )


def attribute_option_validity_declarations(property_base: str) -> list[CodeSystemProperty]:
    """The CodeSystem-level declarations of the two dates a vocabulary carrying a window emits."""
    return [
        CodeSystemProperty(
            code=ATTRIBUTE_OPTION_VALID_FROM_PROPERTY,
            uri=f"{property_base}/{ATTRIBUTE_OPTION_VALID_FROM_PROPERTY}",
            description=_VALID_FROM_DECLARATION_DESCRIPTION,
            type="dateTime",
        ),
        CodeSystemProperty(
            code=ATTRIBUTE_OPTION_VALID_TO_PROPERTY,
            uri=f"{property_base}/{ATTRIBUTE_OPTION_VALID_TO_PROPERTY}",
            description=_VALID_TO_DECLARATION_DESCRIPTION,
            type="dateTime",
        ),
    ]


def restricted_category_option_uids(sources: list[QuestionnaireSourceIn]) -> list[str]:
    """Every category option composing a non-default attribute combo the selection rides, sorted by UID.

    What one run has to read `organisationUnits` for: the options of the combos whose vocabularies it
    publishes, and no other category option the instance holds.
    """
    return sorted(
        {
            option_uid
            for source in sources
            if source.attribute_combo is not None and not source.attribute_combo.is_default
            for option_combo in source.attribute_combo.option_combos
            for option_uid in option_combo.category_option_uids
        }
    )


def build_attribute_option_restriction_artifacts(
    sources: list[QuestionnaireSourceIn],
    restrictions: AttributeOptionRestrictions,
    *,
    id_stem: str,
) -> AttributeOptionRestrictionBuild:
    """Build one List per restricted category option, and the plan the combo concepts name them by.

    `id_stem` is the attribute-combo family's own, so a restriction List sits in that family's
    directory under that family's prefix and the directory sweep keeps the two kinds apart.

    The date axis needs no artifact of its own: a window is two dates, so it rides the plan straight
    onto the concept as the narrowest window of the options the combo is met from.
    """
    build = AttributeOptionRestrictionBuild()
    compositions = _compositions(sources)
    published_uids = restrictions.units.published_uids()
    list_ids: dict[str, str] = {}
    for option_uid in sorted({uid for composition in compositions.values() for uid in composition}):
        restricted_to = restrictions.organisation_units.get(option_uid)
        if not restricted_to:
            continue
        members = restrictions.units.under(restricted_to)
        if members == published_uids:
            continue
        list_id = f"{id_stem}{option_uid}-{ATTRIBUTE_OPTION_RESTRICTION_ID_SUFFIX}"
        list_ids[option_uid] = list_id
        build.artifacts.append(
            _json_artifact(list_id, _restriction_list(list_id, option_uid, members, restrictions.published))
        )
    build.plan = AttributeOptionRestrictionPlan(
        list_ids={
            option_combo_uid: tuple(list_ids[option_uid] for option_uid in composition if option_uid in list_ids)
            for option_combo_uid, composition in compositions.items()
            if any(option_uid in list_ids for option_uid in composition)
        },
        windows=_windows(compositions, restrictions.validity),
    )
    return build


def _windows(
    compositions: dict[str, list[str]], validity: dict[str, CategoryOptionValidity]
) -> dict[str, CategoryOptionValidity]:
    """The narrowest window each attribute option combo is open for, over the options it is met from."""
    windows = {
        option_combo_uid: narrowest_window(validity, composition)
        for option_combo_uid, composition in compositions.items()
    }
    return {option_combo_uid: window for option_combo_uid, window in windows.items() if window.stated}


def _later(left: datetime.date | None, right: datetime.date | None) -> datetime.date | None:
    """The later of two opening days, either of them absent - absence being the earliest day there is."""
    if left is None:
        return right
    return left if right is None else max(left, right)


def _earlier(left: datetime.date | None, right: datetime.date | None) -> datetime.date | None:
    """The earlier of two closing days, either of them absent - absence being the latest day there is."""
    if left is None:
        return right
    return left if right is None else min(left, right)


def _compositions(sources: list[QuestionnaireSourceIn]) -> dict[str, list[str]]:
    """Which category options each published attribute option combo is met from, by option combo UID."""
    compositions: dict[str, list[str]] = {}
    for source in sources:
        combo = source.attribute_combo
        if combo is None or combo.is_default:
            continue
        for option_combo in combo.option_combos:
            compositions.setdefault(option_combo.uid, list(option_combo.category_option_uids))
    return compositions


def _restriction_list(
    list_id: str,
    option_uid: str,
    members: frozenset[str],
    published: StemResolution,
) -> ResourceList:
    """One category option's restriction as a snapshot List of the Locations a capture under it may name.

    Entries are ordered by the Location id they reference, so a regenerate of an unchanged
    restriction produces a byte-identical file whatever order DHIS2 returned the units in.
    """
    references = sorted(published.reference_for("Location", uid) for uid in members)
    return ResourceList(
        id=list_id,
        status="current",
        mode="snapshot",
        title=f"Organisation units category option {option_uid} may be captured at",
        entry=[ListEntry(item=Reference(reference=reference)) for reference in references] or None,
    )


def _json_artifact(list_id: str, resource: ResourceList) -> JsonArtifact:
    """Serialise one restriction List as the predefined-resource file the loader reads."""
    return JsonArtifact(
        relative_path=f"{ATTRIBUTE_COMBO_DIRECTORY}/{ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE}-{list_id}.json",
        content=f"{resource.model_dump_json(exclude_none=True, by_alias=True, indent=2)}\n",
    )
