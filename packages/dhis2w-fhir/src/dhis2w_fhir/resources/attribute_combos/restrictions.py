"""Which organisation units an attribute option combo may be captured at, published as a List per category option.

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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from dhis2w_fhir.names import StemResolution
from dhis2w_fhir.r4 import CodeSystemConceptProperty, CodeSystemProperty, ListEntry, Reference, ResourceList
from dhis2w_fhir.resources.attribute_combos.schemas import ATTRIBUTE_COMBO_DIRECTORY
from dhis2w_fhir.writer import JsonArtifact, JsonBuild

if TYPE_CHECKING:
    from collections.abc import Collection

    from dhis2w_fhir.resources.questionnaires.schemas import QuestionnaireSourceIn

__all__ = [
    "ATTRIBUTE_OPTION_RESTRICTION_ID_SUFFIX",
    "ATTRIBUTE_OPTION_RESTRICTION_PROPERTY",
    "ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE",
    "UNUSABLE_ATTRIBUTE_OPTION_COMBO_REMEDY",
    "AttributeOptionRestrictionBuild",
    "AttributeOptionRestrictionPlan",
    "AttributeOptionRestrictions",
    "OrganisationUnitPaths",
    "UnusableAttributeOptionCombosSummary",
    "UsableAttributeOptionCombos",
    "attribute_option_restriction_declaration",
    "build_attribute_option_restriction_artifacts",
    "restricted_category_option_uids",
    "unusable_attribute_option_combo_message",
    "unusable_attribute_option_combos_summary",
]

#: The concept property naming one restriction List, repeated once per restricted option of the combo.
ATTRIBUTE_OPTION_RESTRICTION_PROPERTY = "dhis2-organisation-units"

#: The resource type a restriction is published as, and the prefix of the reference a property carries.
ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE = "List"

#: The trailing token every restriction List id ends in, after the attribute-combo stem and the option UID.
ATTRIBUTE_OPTION_RESTRICTION_ID_SUFFIX = "org-units"

#: What the restriction property is called on the CodeSystem-level declaration every carrier emits.
_DECLARATION_DESCRIPTION = (
    "List of the organisation units a category option of this combo is restricted to. A capture is "
    "refused unless its organisation unit is on every List the concept names."
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


class AttributeOptionRestrictions(BaseModel):
    """What DHIS2 restricts each attribute category option to, and the registry a restriction is published against."""

    model_config = ConfigDict(frozen=True)

    organisation_units: dict[str, frozenset[str]] = Field(default_factory=dict)
    """The organisation units each attribute category option is restricted to, by category option UID.

    An option absent from the index carries no restriction, which is what DHIS2 answers for an
    option assigned to no organisation unit: every unit may capture under it.
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


class UsableAttributeOptionCombos(BaseModel):
    """Which attribute option combos a capture at each published organisation unit may be filed under.

    The restriction index read the way both consumers of it ask: DHIS2 refuses a capture keyed to a
    combo whose category options are scoped away from the organisation unit it was filed from
    (`E8025`), so the examples target places a response and the questionnaires target grades a form
    against the same question - which combos, at which unit. The ancestor rule is resolved once per
    category option here rather than per combo per unit, because a national registry has thousands
    of units and a category combo has dozens of combos met from a handful of options.
    """

    model_config = ConfigDict(frozen=True)

    admissions: dict[str, frozenset[str]] = Field(default_factory=dict)
    """The published organisation units each restricted category option admits, by category option UID.

    An option absent from the index restricts nothing, which is what DHIS2 answers for an option
    assigned to no organisation unit: every published unit may capture under it.
    """

    @classmethod
    def of(cls, restrictions: AttributeOptionRestrictions) -> UsableAttributeOptionCombos:
        """Resolve every restricted category option's descendants against the published registry, once."""
        return cls(
            admissions={
                option_uid: restrictions.units.under(restricted_to)
                for option_uid, restricted_to in restrictions.organisation_units.items()
                if restricted_to
            }
        )

    def usable_at(self, source: QuestionnaireSourceIn, organisation_unit_uid: str) -> tuple[str, ...]:
        """The option combos of this form's category combo a capture at this organisation unit may be filed under.

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
        )

    def admits(self, organisation_unit_uid: str, category_option_uids: Collection[str]) -> bool:
        """Whether a capture at this organisation unit may be filed under a combo met from these category options."""
        return all(
            organisation_unit_uid in admitted
            for option_uid in category_option_uids
            if (admitted := self.admissions.get(option_uid)) is not None
        )


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


class AttributeOptionRestrictionPlan(BaseModel):
    """Which restriction Lists each attribute option combo concept names, keyed by the option combo's UID."""

    model_config = ConfigDict(frozen=True)

    list_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    def properties_for(self, member_uid: str) -> list[CodeSystemConceptProperty]:
        """The restriction properties one attribute option combo concept carries, one per restricted option."""
        return [
            CodeSystemConceptProperty(
                code=ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
                valueString=f"{ATTRIBUTE_OPTION_RESTRICTION_RESOURCE_TYPE}/{list_id}",
            )
            for list_id in self.list_ids.get(member_uid, ())
        ]


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


def attribute_option_restriction_declaration(property_base: str) -> CodeSystemProperty:
    """The CodeSystem-level declaration every vocabulary carrying a restriction emits."""
    return CodeSystemProperty(
        code=ATTRIBUTE_OPTION_RESTRICTION_PROPERTY,
        uri=f"{property_base}/{ATTRIBUTE_OPTION_RESTRICTION_PROPERTY}",
        description=_DECLARATION_DESCRIPTION,
        type="string",
    )


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
        }
    )
    return build


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
