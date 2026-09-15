"""Markdown emission for the IG's narrative layer: six site pages plus the per-artifact intros.

SUSHI publishes everything under `ig/input/pagecontent/` without a `pages:`
block, and the IG publisher injects a `<Type>-<id>-intro.md` into the top of
the matching artifact page. Both halves are written here, into one sync
directory, and both carry the generated markdown header - so the
hand-authored `index.md` sitting beside them survives every clean and
regenerate.

The pages read the same projections the FSH targets emit from, never a
second endpoint, and every DHIS2-derived string goes through
`names.markdown_text` on the way in: a data set called "Mortality < 5 years
by gender" has to reach the publisher's strict HTML parse escaped, and a name
holding a pipe has to stay inside its table cell.

`capture.md` is the contract page: it states what a third party sends to
capture data against the published forms, worked once per form kind off the
selected metadata, and it derives its answer-typing table from the very
tables the example emitter answers from - so the page and the examples can
never disagree.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, ConfigDict, Field

from dhis2w_fhir.foundation import build_naming_system_declarations
from dhis2w_fhir.foundation.schemas import FoundationNaming
from dhis2w_fhir.names import StemResolution, code_or_uid, markdown_text
from dhis2w_fhir.period.parser import parse_period
from dhis2w_fhir.period.recent import recent_periods
from dhis2w_fhir.period.schemas import PERIOD_TYPE_DEFINITIONS
from dhis2w_fhir.r4 import DEFAULT_SUBJECT_RESOURCE_TYPE
from dhis2w_fhir.resources.attribute_combos import attribute_combo_identities, attribute_combo_sources
from dhis2w_fhir.resources.attribute_combos.restrictions import (
    AttributeOptionRestrictions,
    CategoryOptionValidity,
    UsableAttributeOptionCombos,
)
from dhis2w_fhir.resources.attribute_combos.schemas import AttributeComboIdentity
from dhis2w_fhir.resources.examples import (
    MULTI_VALUE_TYPE,
    STATUS_BY_EVENT_STATUS,
    answer_element,
    example_attribute_combo_assignments,
)
from dhis2w_fhir.resources.examples.schemas import SyntheticPlacement
from dhis2w_fhir.resources.option_sets import option_set_code_fallback, option_set_identities
from dhis2w_fhir.resources.option_sets.schemas import ConceptAssignmentPlan
from dhis2w_fhir.resources.organisation_units import organisation_unit_stem_subjects, plan_organisation_unit_stems
from dhis2w_fhir.resources.organisation_units.naming import OrganisationUnitNaming, location_profile_reference
from dhis2w_fhir.resources.pages.schemas import (
    PERIOD_EXAMPLE_REFERENCE_DATE,
    CaptureAttributeOptionComboExample,
    CaptureFormExample,
    CaptureLinkRow,
    CapturePeriodExample,
    CaptureView,
    CodeSystemIntroView,
    EventStatusRow,
    FormRow,
    FormSectionRow,
    IdentifiersView,
    LevelRow,
    OptionSetRow,
    OrganizationIntroView,
    PagesIn,
    PeriodsView,
    PeriodTypeRow,
    QuestionnaireIntroView,
    RegistryView,
    SupportCodeSystemRow,
    TerminologyView,
    TrackerProgramGroup,
    ValueLiteralRow,
)
from dhis2w_fhir.resources.questionnaires import ITEM_TYPES_BY_VALUE_TYPE
from dhis2w_fhir.resources.questionnaires.schemas import (
    FORM_KIND_PROFILES,
    CategoryOptionComboIn,
    FormKind,
    QuestionnaireItemIn,
    QuestionnaireNaming,
    QuestionnaireSourceIn,
    QuestionnaireStemPlan,
    form_subject_type,
    plan_questionnaire_stems,
    source_display_name,
)
from dhis2w_fhir.writer import FshArtifact, FshBuild

if TYPE_CHECKING:
    from dhis2w_fhir.config import GenerateConfig
    from dhis2w_fhir.resources.organisation_units.schemas import OrganisationUnitIn

__all__ = [
    "INTRO_SUFFIX",
    "PAGES_BASE_SUBDIRECTORY",
    "PAGES_DIRECTORY",
    "SITE_PAGE_FILENAMES",
    "build_page_artifacts",
    "build_registry_page_artifacts",
]

#: Sync directory holding every generated page, relative to `ig/input/`.
PAGES_DIRECTORY = "pagecontent"

#: The directory under the project's `ig/` that `PAGES_DIRECTORY` is resolved against.
PAGES_BASE_SUBDIRECTORY = "input"

#: What names a per-artifact intro the IG publisher injects into an artifact page.
INTRO_SUFFIX = "-intro.md"

#: The site pages, in menu order. Stable kebab file names: the scaffolded menu links them.
SITE_PAGE_FILENAMES = ("forms.md", "registry.md", "terminology.md", "identifiers.md", "periods.md", "capture.md")

#: How each form kind reads in prose on the pages it appears on.
_KIND_LABELS: dict[FormKind, str] = {
    "aggregate": "data set",
    "event": "event program",
    "tracker": "tracker program registration",
    "tracker-event": "tracker program stage",
    "tracked-entity": "tracked entity type registration",
}

#: What a data set with no DHIS2 period type shows in the period-type column.
_ABSENT_TEXT = "-"

#: The literal rules the capture page states for the value types whose spelling is not obvious
#: from the answer element alone. Everything else falls back to `_ELEMENT_LITERAL_RULES`.
_VALUE_TYPE_LITERAL_RULES = {
    "BOOLEAN": "`true` or `false`, unquoted JSON booleans.",
    "TRUE_ONLY": "Always `true` - DHIS2 stores no false value, so an unticked box is simply absent.",
    "DATE": "`YYYY-MM-DD`.",
    "DATETIME": "`YYYY-MM-DDThh:mm:ss` plus a zone; DHIS2 stores local time, so send `Z` when you mean UTC.",
    "TIME": "`hh:mm:ss` - seconds are mandatory in FHIR even where DHIS2 captures `hh:mm`.",
    "AGE": "`YYYY-MM-DD`, the date of birth - DHIS2 renders the age from it, so the date is the captured value.",
    "MULTI_TEXT": (
        "Option-set bound, and the item repeats: send one `answer` per selection, each a "
        "`valueCoding` into the set's CodeSystem."
    ),
    "URL": "An absolute URI.",
    "ORGANISATION_UNIT": "`Location/<organisationUnitId>` - the Location this guide publishes for that unit.",
    "COORDINATE": "The DHIS2 `[longitude,latitude]` string; no R4 item type expresses a coordinate pair.",
    "GEOJSON": "The GeoJSON document as stored, carried verbatim in the string.",
    "PERCENTAGE": "A decimal between 0 and 100, the bounds the item's `minValue` / `maxValue` state.",
    "UNIT_INTERVAL": "A decimal between 0 and 1, the bounds the item's `minValue` / `maxValue` state.",
    "FILE_RESOURCE": "An `Attachment`; the generated examples leave file answers empty rather than invent one.",
    "IMAGE": "An `Attachment`; the generated examples leave image answers empty rather than invent one.",
    "REFERENCE": "The bare DHIS2 UID - this guide publishes no FHIR resource for the referenced object.",
    "TRACKER_ASSOCIATE": "The bare DHIS2 UID - this guide publishes no FHIR resource for the referenced object.",
}

#: The literal rule every remaining value type takes, from the answer element it lands on.
_ELEMENT_LITERAL_RULES = {
    "valueInteger": "A whole number; the item's `minValue` / `maxValue` state any bound the value type carries.",
    "valueDecimal": "A decimal number.",
    "valueString": "The stored DHIS2 text.",
    "valueUri": "An absolute URI.",
    "valueReference": "A reference to the resource this guide publishes for the referenced object.",
}

#: The answer element an item type fixes whatever the value type, because R4 admits only one.
#: `#attachment` is the case that matters: the example emitter never invents a file, so its
#: typing tables have no opinion, while the item type leaves a capture client exactly one choice.
_ANSWER_ELEMENTS_BY_ITEM_TYPE = {"attachment": "valueAttachment"}

#: How many worked `linkId` rows the capture page shows per form - enough to state both grammars.
_CAPTURE_LINK_ROWS = 4

#: The two `linkId` grammars a capture client answers on.
_PLAIN_LINK_GRAMMAR = "<dataElementId>"
_DISAGGREGATED_LINK_GRAMMAR = "<dataElementId>.<categoryOptionComboId>"

_ENVIRONMENT = Environment(
    loader=PackageLoader("dhis2w_fhir.resources.pages", "templates"),
    autoescape=select_autoescape(default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def build_page_artifacts(
    pages: PagesIn,
    config: GenerateConfig,
    canonical: str,
    *,
    stem_plan: QuestionnaireStemPlan | None = None,
    organisation_unit_stems: StemResolution | None = None,
    example_placements: dict[str, SyntheticPlacement] | None = None,
    attribute_option_restrictions: AttributeOptionRestrictions | None = None,
) -> FshBuild:
    """Build the six site pages plus every per-artifact intro the fetched metadata earns.

    `stem_plan` and `organisation_unit_stems` are the identity resolutions the artifact links,
    the intro file names, and the worked `Location/...` references follow; left None they resolve
    here through the same calls the emitting targets resolve through. Their fall-back notes are
    not raised here - the target that owns each surface reports them.

    `example_placements` is where the run's own examples file each form from, so the capture page
    works its steps against an organisation unit the form is assigned to rather than against the
    first unit in the registry: the page teaches the capture the examples beside it make.

    `attribute_option_restrictions` is what DHIS2 scopes each attribute category option to, which
    is how the capture page quotes an attribute option combination the worked organisation unit
    may file under for the worked period. Handed none, the page quotes the first combination the
    form's own vocabulary holds for that unit and grades no calendar window.
    """
    build = FshBuild()
    plan = stem_plan if stem_plan is not None else plan_questionnaire_stems(pages.forms, config.naming.source)
    if organisation_unit_stems is not None:
        unit_stems = organisation_unit_stems
    else:
        subjects = organisation_unit_stem_subjects(pages.organisation_units)
        unit_stems = plan_organisation_unit_stems(
            subjects, config.naming.source, registry=config.organisation_units.registry
        )
    forms = [
        _form_row(source, plan.targets.stem_for(source.uid))
        for source in sorted(pages.forms, key=lambda item: (item.name, item.uid))
    ]
    build.artifacts.append(_forms_page(forms))
    build.artifacts.append(_registry_page(pages.organisation_units, config, unit_stems))
    build.artifacts.append(_terminology_page(pages, config))
    build.artifacts.append(_identifiers_page(config))
    build.artifacts.append(_periods_page(config))
    build.artifacts.append(
        _capture_page(
            pages,
            config,
            canonical,
            plan,
            unit_stems,
            example_placements or {},
            attribute_option_restrictions or AttributeOptionRestrictions(),
        )
    )
    build.artifacts.extend(_questionnaire_intros(forms))
    build.artifacts.extend(_code_system_intros(pages, config))
    build.artifacts.extend(_organization_intros(pages.organisation_units, unit_stems))
    return build


def _page(filename: str, template_name: str, **values: object) -> FshArtifact:
    """Render one page template into the sync directory's artifact."""
    return FshArtifact(
        relative_path=f"{PAGES_DIRECTORY}/{filename}",
        kind="page",
        fsh_name=filename,
        content=_ENVIRONMENT.get_template(template_name).render(**values),
    )


def _source_items(source: QuestionnaireSourceIn) -> list[QuestionnaireItemIn]:
    """Every question one form carries, sectioned and unsectioned alike."""
    return [item for section in source.sections for item in section.items] + list(source.flat_items)


def _form_row(source: QuestionnaireSourceIn, stem: str) -> FormRow:
    """Project one form onto the catalog row, escaping every DHIS2-derived string for markdown."""
    return FormRow(
        uid=source.uid,
        stem=stem,
        kind=source.kind,
        name=markdown_text(source.name),
        cell_name=markdown_text(source.name, table_cell=True),
        code=markdown_text(code_or_uid(source.code, source.uid), table_cell=True),
        description=markdown_text(source.description or ""),
        period_type=markdown_text(source.period_type or _ABSENT_TEXT, table_cell=True),
        program_uid=source.uid if source.kind == "tracker" else (source.program.uid if source.program else ""),
        program_name=markdown_text(
            source.name if source.kind == "tracker" else (source.program.name if source.program else ""),
            table_cell=True,
        ),
        section_count=len(source.sections),
        question_count=len(_source_items(source)),
        unsectioned_question_count=len(source.flat_items),
        sections=[
            FormSectionRow(name=markdown_text(section.name, table_cell=True), question_count=len(section.items))
            for section in source.sections
        ],
    )


def _forms_page(forms: list[FormRow]) -> FshArtifact:
    """Build `forms.md`: the catalog of each form kind, tracker stages grouped under their program."""
    return _page(
        "forms.md",
        "forms.md.jinja",
        data_sets=[form for form in forms if form.kind == "aggregate"],
        event_programs=[form for form in forms if form.kind == "event"],
        tracker_programs=_tracker_program_groups(forms),
        tracked_entity_types=[form for form in forms if form.kind == "tracked-entity"],
    )


def _tracker_program_groups(forms: list[FormRow]) -> list[TrackerProgramGroup]:
    """Group each tracker program's forms: the registration that enrols, then the stages in catalog order.

    Programs sort by name then UID, so the catalog reads in the same order whichever of a
    program's forms the run reached first.
    """
    stages_by_program: dict[str, list[FormRow]] = {}
    registrations: dict[str, FormRow] = {}
    names_by_program: dict[str, str] = {}
    for form in forms:
        if form.kind == "tracker":
            registrations.setdefault(form.program_uid, form)
        elif form.kind == "tracker-event":
            stages_by_program.setdefault(form.program_uid, []).append(form)
        else:
            continue
        names_by_program.setdefault(form.program_uid, form.program_name)
    ordered = sorted(names_by_program, key=lambda uid: (names_by_program[uid], uid))
    return [
        TrackerProgramGroup(
            uid=uid,
            name=names_by_program[uid],
            registration=registrations.get(uid),
            stages=stages_by_program.get(uid, []),
        )
        for uid in ordered
    ]


def build_registry_page_artifacts(
    pages: PagesIn, config: GenerateConfig, *, organisation_unit_stems: StemResolution | None = None
) -> FshBuild:
    """Build the pages of a registry package: its Registry page plus one intro per published unit.

    A registry package publishes organisation units and nothing else, so its site has no form
    catalog, terminology, identifier or capture page to narrate.
    """
    build = FshBuild()
    if organisation_unit_stems is not None:
        unit_stems = organisation_unit_stems
    else:
        unit_stems = plan_organisation_unit_stems(
            organisation_unit_stem_subjects(pages.organisation_units), config.naming.source
        )
    build.artifacts.append(_registry_page(pages.organisation_units, config, unit_stems))
    build.artifacts.extend(_organization_intros(pages.organisation_units, unit_stems))
    return build


def _registry_page(
    organisation_units: list[OrganisationUnitIn], config: GenerateConfig, organisation_unit_stems: StemResolution
) -> FshArtifact:
    """Build `registry.md`: the organisation-unit totals, the level table, and the profile pointers.

    A guide whose units are published by another package states that package instead of the
    totals - it read the stems of the published selection and nothing else about the units.
    """
    names = OrganisationUnitNaming.from_naming(config.naming)
    registry = config.organisation_units.registry
    if registry is not None:
        view = RegistryView(
            unit_count=len(organisation_unit_stems.stems),
            organization_profile=names.organization_profile,
            location_profile=names.location_profile,
            registry_id=registry.id,
            registry_version=registry.version,
            registry_canonical=registry.canonical,
        )
        return _page("registry.md", "registry.md.jinja", registry=view)
    levels: dict[int, int] = {}
    for organisation_unit in organisation_units:
        levels[organisation_unit.level] = levels.get(organisation_unit.level, 0) + 1
    root = min(organisation_units, key=lambda item: (item.level, item.path, item.uid), default=None)
    view = RegistryView(
        unit_count=len(organisation_units),
        root_name=markdown_text(root.name) if root is not None else "",
        root_uid=root.uid if root is not None else "",
        position_count=sum(1 for item in organisation_units if item.latitude is not None),
        boundary_count=sum(1 for item in organisation_units if item.boundary_geojson is not None),
        organization_profile=names.organization_profile,
        location_profile=names.location_profile,
        levels=[LevelRow(level=level, unit_count=levels[level]) for level in sorted(levels)],
    )
    return _page("registry.md", "registry.md.jinja", registry=view)


def _terminology_page(pages: PagesIn, config: GenerateConfig) -> FshArtifact:
    """Build `terminology.md`: the option-set catalog plus the support CodeSystems this run emits."""
    by_uid = {option_set.uid: option_set for option_set in pages.option_sets}
    rows = [
        OptionSetRow(
            uid=identity.uid,
            cell_name=markdown_text(identity.name, table_cell=True),
            code_system_id=identity.code_system_id,
            concept_count=len(by_uid[identity.uid].options),
            code_fallback=option_set_code_fallback(by_uid[identity.uid], config),
        )
        for identity in option_set_identities(pages.option_sets, config).identities
    ]
    view = TerminologyView(
        concept_code_source=config.concept_code_source,
        option_sets=rows,
        support_code_systems=_support_code_systems(pages, config),
    )
    return _page("terminology.md", "terminology.md.jinja", terminology=view)


def _support_code_systems(pages: PagesIn, config: GenerateConfig) -> list[SupportCodeSystemRow]:
    """The support CodeSystems this run emits, in artifact order - the data-dictionary pairs, then foundation."""
    questionnaire_names = QuestionnaireNaming.from_naming(config.naming)
    foundation = FoundationNaming.from_naming(config.naming)
    asks_attributes = {
        kind for kind, profile in FORM_KIND_PROFILES.items() if profile.question_subject == "tracked-entity-attribute"
    }
    items = [item for source in pages.forms if source.kind not in asks_attributes for item in _source_items(source)]
    attributes = [item for source in pages.forms if source.kind in asks_attributes for item in _source_items(source)]
    rows: list[SupportCodeSystemRow] = []
    if items:
        rows.append(
            SupportCodeSystemRow(
                label="Data elements",
                fsh_name=questionnaire_names.data_element_code_system,
                code_system_id=questionnaire_names.data_element_code_system_id,
                description="Every DHIS2 data element the generated questionnaires ask for.",
            )
        )
    if attributes:
        rows.append(
            SupportCodeSystemRow(
                label="Tracked entity attributes",
                fsh_name=questionnaire_names.tracked_entity_attribute_code_system,
                code_system_id=questionnaire_names.tracked_entity_attribute_code_system_id,
                description="Every DHIS2 tracked entity attribute the generated registration forms ask for.",
            )
        )
    if any(_is_disaggregated(item) for item in items):
        rows.append(
            SupportCodeSystemRow(
                label="Category option combos",
                fsh_name=questionnaire_names.category_option_combo_code_system,
                code_system_id=questionnaire_names.category_option_combo_code_system_id,
                description="Every DHIS2 category option combo the generated questionnaires disaggregate by.",
            )
        )
    rows.append(
        SupportCodeSystemRow(
            label="Form types",
            fsh_name=foundation.form_type_code_system,
            code_system_id=foundation.form_type_code_system_id,
            description="The kind of DHIS2 form a Questionnaire and its responses came from.",
        )
    )
    rows.append(
        SupportCodeSystemRow(
            label="Period types",
            fsh_name=foundation.period_type_code_system,
            code_system_id=foundation.period_type_code_system_id,
            description="The reporting period types the D2Period extension is typed by.",
        )
    )
    return rows


def _is_disaggregated(item: QuestionnaireItemIn) -> bool:
    """Check whether a data element carries a real (non-default) category combo."""
    return item.category_combo is not None and not item.category_combo.is_default


def _identifiers_page(config: GenerateConfig) -> FshArtifact:
    """Build `identifiers.md`: the two identifier slices, the property URIs, and the NamingSystem table."""
    view = IdentifiersView(
        identifier_system_base=config.identifier_system_base,
        concept_code_source=config.concept_code_source,
        naming_systems=build_naming_system_declarations(config),
    )
    return _page("identifiers.md", "identifiers.md.jinja", identifiers=view)


def _periods_page(config: GenerateConfig) -> FshArtifact:
    """Build `periods.md`: the D2Period extension's shape and every period type the parser registers."""
    names = FoundationNaming.from_naming(config.naming)
    view = PeriodsView(
        period_extension=names.period_extension,
        period_extension_id=names.period_extension_id,
        period_type_code_system=names.period_type_code_system,
        period_type_code_system_id=names.period_type_code_system_id,
        period_type_value_set=names.period_type_value_set,
        period_types=[_period_type_row(definition.name) for definition in PERIOD_TYPE_DEFINITIONS],
    )
    return _page("periods.md", "periods.md.jinja", periods=view)


def _period_type_row(period_type: str) -> PeriodTypeRow:
    """One period type's row: the newest ISO period completed by the fixed reference date, and its span."""
    recent = recent_periods(period_type, 1, PERIOD_EXAMPLE_REFERENCE_DATE)
    if not recent:
        return PeriodTypeRow(name=period_type, example_iso=_ABSENT_TEXT, span=_ABSENT_TEXT)
    value = parse_period(recent[0])
    return PeriodTypeRow(
        name=period_type,
        example_iso=value.iso,
        span=f"{value.start_date.isoformat()} to {value.end_date.isoformat()}",
    )


def _capture_page(
    pages: PagesIn,
    config: GenerateConfig,
    canonical: str,
    stem_plan: QuestionnaireStemPlan,
    organisation_unit_stems: StemResolution,
    example_placements: dict[str, SyntheticPlacement],
    attribute_option_restrictions: AttributeOptionRestrictions,
) -> FshArtifact:
    """Build `capture.md`: what a capture client sends, worked once per form kind, and how answers are typed."""
    foundation = FoundationNaming.from_naming(config.naming)
    units = _CaptureUnitResolver.of(pages, organisation_unit_stems, example_placements)
    combos = _CaptureComboResolver.of(pages, config, canonical, example_placements, attribute_option_restrictions)
    tracker_event = _capture_form_example(pages.forms, "tracker-event", canonical, stem_plan, config, units, combos)
    view = CaptureView(
        canonical=canonical,
        period_extension=foundation.period_extension,
        period_extension_id=foundation.period_extension_id,
        form_type_extension=foundation.form_type_extension,
        form_type_code_system=foundation.form_type_code_system,
        aggregate_profile=foundation.aggregate_response_profile,
        aggregate_profile_id=foundation.aggregate_response_profile_id,
        event_profile=foundation.event_response_profile,
        event_profile_id=foundation.event_response_profile_id,
        tracker_event_profile=foundation.tracker_event_response_profile,
        tracker_event_profile_id=foundation.tracker_event_response_profile_id,
        enrollment_extension=foundation.tracker_enrollment_extension,
        enrollment_extension_id=foundation.tracker_enrollment_extension_id,
        organisation_unit_extension=foundation.organisation_unit_extension,
        organisation_unit_extension_id=foundation.organisation_unit_extension_id,
        attribute_option_combo_extension=foundation.attribute_option_combo_extension,
        attribute_option_combo_extension_id=foundation.attribute_option_combo_extension_id,
        attribute_option_combos_extension=foundation.attribute_option_combos_extension,
        tracked_entity_system=f"{config.identifier_system_base}/id/tracked-entity",
        enrollment_system=f"{config.identifier_system_base}/id/tracker-enrollment",
        capture_server=foundation.capture_server,
        capture_server_id=foundation.capture_server_id,
        location_profile=location_profile_reference(config),
        tracker_subject_type=(
            tracker_event.subject_type if tracker_event is not None else DEFAULT_SUBJECT_RESOURCE_TYPE
        ),
        aggregate=_capture_form_example(pages.forms, "aggregate", canonical, stem_plan, config, units, combos),
        event=_capture_form_example(pages.forms, "event", canonical, stem_plan, config, units, combos),
        tracker_event=tracker_event,
        event_statuses=[
            EventStatusRow(event_status=event_status, response_status=STATUS_BY_EVENT_STATUS[event_status])
            for event_status in sorted(STATUS_BY_EVENT_STATUS)
        ],
        value_literals=[_value_literal_row(value_type, config) for value_type in sorted(ITEM_TYPES_BY_VALUE_TYPE)],
    )
    return _page("capture.md", "capture.md.jinja", capture=view)


class _WorkedCaptureUnit(BaseModel):
    """The organisation unit one worked walk-through files its capture from, as the page cites it."""

    model_config = ConfigDict(frozen=True)

    uid: str = ""
    reference: str = ""
    name: str = ""


class _CaptureUnitResolver(BaseModel):
    """Which organisation unit each worked form files from, read off the run's own example placements.

    A capture outside the form's DHIS2 assignment is refused with `E1029`, so a page teaching a
    `subject` the reader copies has to name a unit the form is assigned to. The examples target
    already answered that question for every form it published, so the page answers it from there
    rather than reaching for the first unit in the registry. A form the run placed no example for -
    no assignment read, or a guide whose registry is another package - falls back to the lowest
    published unit, which is what the page can say without an assignment to read.
    """

    model_config = ConfigDict(frozen=True)

    placements: dict[str, SyntheticPlacement] = Field(default_factory=dict)
    names: dict[str, str] = Field(default_factory=dict)
    stems: StemResolution = Field(default_factory=StemResolution)
    fallback_uid: str = ""

    @classmethod
    def of(
        cls,
        pages: PagesIn,
        organisation_unit_stems: StemResolution,
        example_placements: dict[str, SyntheticPlacement],
    ) -> _CaptureUnitResolver:
        """Index the run's placements, the published unit names, and the unit an unplaced form falls back to."""
        lowest = min(pages.organisation_units, key=lambda item: (item.level, item.path, item.uid), default=None)
        return cls(
            placements=example_placements,
            names={unit.uid: unit.name for unit in pages.organisation_units},
            stems=organisation_unit_stems,
            # A guide whose registry is another package read no unit beyond its stem, so the worked
            # reference is the first published stem and the prose cites the UID alone.
            fallback_uid=lowest.uid if lowest is not None else min(organisation_unit_stems.stems, default=""),
        )

    def places(self, form_uid: str) -> bool:
        """Whether the run published an example for this form, and so knows a unit it may report from."""
        return form_uid in self.placements

    def worked(self, form_uid: str) -> _WorkedCaptureUnit:
        """The organisation unit this form's walk-through files from - its example's own, else the fall-back."""
        placement = self.placements.get(form_uid)
        uid = placement.organisation_unit_uids[0] if placement is not None else self.fallback_uid
        if not uid:
            return _WorkedCaptureUnit()
        name = self.names.get(uid)
        return _WorkedCaptureUnit(
            uid=uid,
            reference=self.stems.reference_for("Location", uid),
            name=markdown_text(name) if name else "",
        )


class _WorkedCaptureCombo(BaseModel):
    """What the capture page may say about the combination one form's walk-through files under.

    The two answers are different facts and the page says different things about them: `example` is
    a combination the worked organisation unit may file under for the worked period, and
    `restricted_away` is the form DHIS2 leaves no such combination at all - a form nobody may
    capture for, which the page states rather than quoting a combination the instance refuses.
    """

    model_config = ConfigDict(frozen=True)

    example: CaptureAttributeOptionComboExample | None = None
    restricted_away: bool = False


class _CaptureComboResolver(BaseModel):
    """Which attribute option combination each worked form files its capture under, and how the page cites it.

    DHIS2 keys a data value set by `(organisation unit, period, attribute option combination)` and
    refuses a write naming none of the third where the form's category combo is not the default one
    (`E8023`). It also scopes a category option to organisation units (`E8025`) and to a calendar
    window (`E8032`), so the combination the page quotes has to be one the worked organisation unit
    may file under for the worked period - which is what the run's own example placements and the
    instance's restrictions answer between them.

    Both axes are graded together and an empty answer is the form's own verdict rather than a gap in
    what is known: a form whose every combination this DHIS2 instance scopes away from the worked
    organisation unit, or has closed by the worked period, is one no capture exists for, and the
    examples target drops it for the same reason.
    """

    model_config = ConfigDict(frozen=True)

    canonical: str = ""
    placements: dict[str, SyntheticPlacement] = Field(default_factory=dict)
    identities: dict[str, AttributeComboIdentity] = Field(default_factory=dict)
    concept_codes: dict[str, ConceptAssignmentPlan] = Field(default_factory=dict)
    restrictions: AttributeOptionRestrictions = Field(default_factory=AttributeOptionRestrictions)
    usable: UsableAttributeOptionCombos = Field(default_factory=UsableAttributeOptionCombos)

    @classmethod
    def of(
        cls,
        pages: PagesIn,
        config: GenerateConfig,
        canonical: str,
        example_placements: dict[str, SyntheticPlacement],
        attribute_option_restrictions: AttributeOptionRestrictions,
    ) -> _CaptureComboResolver:
        """Index the published combination vocabularies and the concept codes their examples name them by."""
        sources = attribute_combo_sources(pages.forms)
        plan = attribute_combo_identities(sources, config)
        return cls(
            canonical=canonical,
            placements=example_placements,
            identities={identity.uid: identity for identity in plan.identities},
            concept_codes=example_attribute_combo_assignments(pages.forms, config),
            restrictions=attribute_option_restrictions,
            usable=UsableAttributeOptionCombos.of(attribute_option_restrictions),
        )

    def worked(
        self, source: QuestionnaireSourceIn, organisation_unit_uid: str, period: CapturePeriodExample | None
    ) -> _WorkedCaptureCombo:
        """The combination this form's walk-through files under, or the verdict that DHIS2 leaves it none."""
        combo = source.attribute_combo
        if combo is None or combo.is_default or not combo.option_combos:
            return _WorkedCaptureCombo()
        admitted = self._usable_option_combos(source, organisation_unit_uid, period)
        if not admitted:
            return _WorkedCaptureCombo(restricted_away=True)
        identity = self.identities.get(combo.uid)
        assignment = self.concept_codes.get(combo.uid)
        if identity is None or assignment is None:
            return _WorkedCaptureCombo()
        option_combo = admitted[0]
        concept_code = assignment.code_for(option_combo.uid)
        if concept_code is None:
            return _WorkedCaptureCombo()
        return _WorkedCaptureCombo(
            example=CaptureAttributeOptionComboExample(
                uid=option_combo.uid,
                display=markdown_text(option_combo.name),
                concept_code=concept_code,
                code_system_url=f"{self.canonical}/CodeSystem/{identity.code_system_id}",
                value_set_id=identity.value_set_id,
            )
        )

    def _usable_option_combos(
        self, source: QuestionnaireSourceIn, organisation_unit_uid: str, period: CapturePeriodExample | None
    ) -> list[CategoryOptionComboIn]:
        """Every combination of this form's vocabulary the worked unit may file under for the worked period.

        Both axes DHIS2 grades are graded here, off the instance's own restrictions: a combination
        scoped away from the worked organisation unit is answered `E8025`, and one whose calendar
        window does not cover the whole worked period `E8032`. The run's own placement narrows it
        further where it has one, so the page cites what the examples beside it cite. An empty
        answer is the form nothing may capture, and a caller that knows no restriction at all
        narrows nothing - which is the whole vocabulary, as DHIS2 answers for an unrestricted one.
        """
        combo = source.attribute_combo
        if combo is None:
            return []
        placement = self.placements.get(source.uid)
        placed = placement.usable_attribute_option_combo_uids.get(organisation_unit_uid, ()) if placement else ()
        return [
            entry
            for entry in combo.option_combos
            if (not placed or entry.uid in placed)
            and self.usable.admits(organisation_unit_uid, entry.category_option_uids)
            and self._covers(entry, period)
        ]

    def _covers(self, option_combo: CategoryOptionComboIn, period: CapturePeriodExample | None) -> bool:
        """Whether DHIS2 leaves this combination open for the whole period the walk-through reports for."""
        if period is None:
            return True
        window = CategoryOptionValidity()
        for option_uid in option_combo.category_option_uids:
            stated = self.restrictions.validity.get(option_uid)
            if stated is not None:
                window = window.narrowed_by(stated)
        return window.covers(date.fromisoformat(period.start_date), date.fromisoformat(period.end_date))


def _capture_form_example(
    forms: list[QuestionnaireSourceIn],
    kind: FormKind,
    canonical: str,
    stem_plan: QuestionnaireStemPlan,
    config: GenerateConfig,
    units: _CaptureUnitResolver,
    combos: _CaptureComboResolver,
) -> CaptureFormExample | None:
    """Work one selected form of `kind` through the contract: its Questionnaire, its period, and its linkIds.

    A form DHIS2 takes a capture for is preferred over one it refuses every capture of, and a form
    the run filed an example for over one it did not - so the steps are worked against a form the
    reader can really capture for wherever the selection holds one. Where it holds none, the page
    says so rather than quoting a combination the instance answers `E8025` or `E8032` to.
    """
    candidates = [source for source in forms if source.kind == kind and _source_items(source)]
    if not candidates:
        return None
    source = min(candidates, key=lambda item: _capture_preference(item, units, combos))
    worked = units.worked(source.uid)
    period = _capture_period(source)
    attribute_option_combo = combos.worked(source, worked.uid, period)
    return CaptureFormExample(
        uid=source.uid,
        name=markdown_text(source_display_name(source)),
        questionnaire_url=f"{canonical}/Questionnaire/{stem_plan.targets.stem_for(source.uid)}",
        form_type_code=source.kind,
        subject_type=form_subject_type(source, config.tracked_entity_types),
        period=period,
        links=_capture_links(source),
        organisation_unit_uid=worked.uid,
        organisation_unit_reference=worked.reference,
        organisation_unit_name=worked.name,
        attribute_option_combo=attribute_option_combo.example,
        attribute_option_combo_restricted_away=attribute_option_combo.restricted_away,
    )


def _capture_preference(
    source: QuestionnaireSourceIn, units: _CaptureUnitResolver, combos: _CaptureComboResolver
) -> tuple[int, int, str, str]:
    """How one form ranks as the walk-through's worked example - capturable first, placed next, then by name."""
    worked = units.worked(source.uid)
    restricted_away = combos.worked(source, worked.uid, _capture_period(source)).restricted_away
    return (1 if restricted_away else 0, 0 if units.places(source.uid) else 1, source.name, source.uid)


def _capture_period(source: QuestionnaireSourceIn) -> CapturePeriodExample | None:
    """The worked reporting period of one data set, pinned to the reference date so the page never moves."""
    if not source.period_type:
        return None
    recent = recent_periods(source.period_type, 1, PERIOD_EXAMPLE_REFERENCE_DATE)
    if not recent:
        return None
    value = parse_period(recent[0])
    return CapturePeriodExample(
        iso=value.iso,
        period_type=value.period_type,
        start_date=value.start_date.isoformat(),
        end_date=value.end_date.isoformat(),
    )


def _capture_links(source: QuestionnaireSourceIn) -> list[CaptureLinkRow]:
    """The first few worked `linkId`s of one form, both grammars represented where the form has both."""
    rows: list[CaptureLinkRow] = []
    for item in _source_items(source):
        if _is_disaggregated(item) and item.category_combo is not None:
            rows.extend(
                CaptureLinkRow(
                    link_id=f"{item.uid}.{option_combo.uid}",
                    label=markdown_text(f"{item.name} / {option_combo.name}", table_cell=True),
                    grammar=_DISAGGREGATED_LINK_GRAMMAR,
                    answer_element=_answer_element_label(item),
                    required=item.compulsory or option_combo.uid in item.required_option_combo_uids,
                )
                for option_combo in item.category_combo.option_combos
            )
            continue
        rows.append(
            CaptureLinkRow(
                link_id=item.uid,
                label=markdown_text(item.name, table_cell=True),
                grammar=_PLAIN_LINK_GRAMMAR,
                answer_element=_answer_element_label(item),
                required=item.compulsory,
            )
        )
    return rows[:_CAPTURE_LINK_ROWS]


def _answer_element_label(item: QuestionnaireItemIn) -> str:
    """The answer element one question takes: a coding when it binds an option set, else its value type's."""
    return "valueCoding" if item.option_set_uid is not None else answer_element(item.value_type)


def _value_literal_row(value_type: str, config: GenerateConfig) -> ValueLiteralRow:
    """One row of the answer-typing table, read off the very tables the example emitter answers from."""
    element = answer_element(value_type)
    item_type = ITEM_TYPES_BY_VALUE_TYPE[value_type]
    if value_type == MULTI_VALUE_TYPE:
        answered_as = "valueCoding"
    else:
        answered_as = _ANSWER_ELEMENTS_BY_ITEM_TYPE.get(item_type) or element
    return ValueLiteralRow(
        value_type=value_type,
        item_type=item_type,
        answer_element=answered_as,
        literal_rule=_literal_rule(value_type, element, config),
    )


def _literal_rule(value_type: str, element: str, config: GenerateConfig) -> str:
    """The typing rule of one value type; an organisation-unit answer names the form its references take."""
    registry = config.organisation_units.registry
    if value_type == "ORGANISATION_UNIT" and registry is not None:
        return (
            f"`{registry.canonical}/Location/<organisationUnitId>` - the Location the registry package "
            f"`{registry.id}` publishes for that unit."
        )
    return _VALUE_TYPE_LITERAL_RULES.get(value_type) or _ELEMENT_LITERAL_RULES[element]


def _questionnaire_intros(forms: list[FormRow]) -> list[FshArtifact]:
    """Build one `Questionnaire-<stem>-intro.md` per generated Questionnaire - every form earns one."""
    return [
        _page(
            f"Questionnaire-{form.stem}{INTRO_SUFFIX}",
            "questionnaire-intro.md.jinja",
            intro=QuestionnaireIntroView(form=form, kind_label=_KIND_LABELS[form.kind], form_type_code=form.kind),
        )
        for form in forms
    ]


def _code_system_intros(pages: PagesIn, config: GenerateConfig) -> list[FshArtifact]:
    """Build a `CodeSystem-<id>-intro.md` for every option set carrying a DHIS2 description, and no others."""
    by_uid = {option_set.uid: option_set for option_set in pages.option_sets}
    artifacts: list[FshArtifact] = []
    for identity in option_set_identities(pages.option_sets, config).identities:
        description = (by_uid[identity.uid].description or "").strip()
        if not description:
            continue
        artifacts.append(
            _page(
                f"CodeSystem-{identity.code_system_id}{INTRO_SUFFIX}",
                "code-system-intro.md.jinja",
                intro=CodeSystemIntroView(
                    code_system_id=identity.code_system_id,
                    uid=identity.uid,
                    name=markdown_text(identity.name),
                    description=markdown_text(description),
                ),
            )
        )
    return artifacts


def _organization_intros(
    organisation_units: list[OrganisationUnitIn], organisation_unit_stems: StemResolution
) -> list[FshArtifact]:
    """Build an `Organization-<stem>-intro.md` for every organisation unit carrying a DHIS2 description."""
    artifacts: list[FshArtifact] = []
    for organisation_unit in sorted(organisation_units, key=lambda item: (item.path, item.uid)):
        description = (organisation_unit.description or "").strip()
        if not description:
            continue
        artifacts.append(
            _page(
                f"Organization-{organisation_unit_stems.stem_for(organisation_unit.uid)}{INTRO_SUFFIX}",
                "organization-intro.md.jinja",
                intro=OrganizationIntroView(
                    uid=organisation_unit.uid,
                    stem=organisation_unit_stems.stem_for(organisation_unit.uid),
                    name=markdown_text(organisation_unit.name),
                    level=organisation_unit.level,
                    description=markdown_text(description),
                ),
            )
        )
    return artifacts
