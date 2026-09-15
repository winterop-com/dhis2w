"""The organisation-unit assignment artifact: one `List` of Locations per form, emitted only when it narrows.

DHIS2 scopes every data set and program to the organisation units it is assigned to, and a capture
against a unit outside that scope is refused at forward time (`E1029`). This module publishes the
scope so a client can honour it: one `List` whose entries are the Locations of the assigned units,
named from the form's `D2OrganisationUnitAssignment` extension.

The economy that makes it publishable is the emission rule: **a List is written only when the
assignment is a proper subset of the published organisation-unit registry.** Assigned everywhere -
the common national case - publishes nothing, and absence means the whole registry, which is what
a consumer already assumed. Tracker stages share their program's List, because DHIS2 hangs the
assignment on the program and not on the stage.

`List` rather than `Group`: R4 binds `Group.member.entity` to Patient, Practitioner,
PractitionerRole, Device, Medication, Substance, and Group, so a Location cannot legally be a
Group member, while `List.entry.item` is `Reference(Resource)` and takes one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from dhis2w_fhir.names import StemResolution
from dhis2w_fhir.notes import GenerateNoteCategory, generate_note
from dhis2w_fhir.r4 import Identifier, ListEntry, Reference, ResourceList
from dhis2w_fhir.resources.questionnaires.schemas import (
    FORM_KIND_PROFILES,
    FormKind,
    QuestionnaireNaming,
    QuestionnaireSourceIn,
    QuestionnaireStemPlan,
    source_program,
)
from dhis2w_fhir.writer import JsonArtifact, JsonBuild

if TYPE_CHECKING:
    from dhis2w_fhir.config import GenerateConfig

__all__ = [
    "ASSIGNMENT_DIRECTORY",
    "ASSIGNMENT_ID_SUFFIX",
    "ASSIGNMENT_LIST_RESOURCE_TYPE",
    "EMPTY_ASSIGNMENT_REMEDY",
    "AssignmentBuild",
    "AssignmentContainer",
    "AssignmentContainerKind",
    "AssignmentIndex",
    "AssignmentPlan",
    "EmptyAssignmentSummary",
    "admitted_organisation_unit_uids",
    "assignment_container",
    "assignment_container_kind",
    "assignment_container_uid",
    "build_assignment_artifacts",
]

#: The `ig/input/resources/` subdirectory the assignment Lists own outright - one JSON file per container.
ASSIGNMENT_DIRECTORY = "assignments"

#: The resource type an assignment artifact is published as, and the prefix of its literal reference.
ASSIGNMENT_LIST_RESOURCE_TYPE = "List"

#: The trailing token every assignment List id ends in, after the prefix, kind token, and container stem.
ASSIGNMENT_ID_SUFFIX = "org-units"

#: The one line that answers a form nobody may report, stated identically wherever the fact is
#: reported - `d2w fhir generate` closes a run with it and `d2w fhir check-artifacts` files it as a
#: finding's remedy. Two selections meet here and the sentence names both: the organisation-unit
#: selection is the one to widen, the form selection the one to narrow.
EMPTY_ASSIGNMENT_REMEDY = (
    "Widen the organisation-unit selection - raise `[generate.organisation_units] max_level`, or set "
    "its `root` higher up the hierarchy - or narrow the form selection in fhir.toml to the forms "
    "those organisation units report, then run `d2w fhir generate` again."
)

AssignmentContainerKind = Literal["data-set", "program"]
"""Which DHIS2 object holds the assignment: a data set for an aggregate form, a program for both others."""


class AssignmentIndex(BaseModel):
    """The organisation units DHIS2 assigns each selected data set and program to, read id-only.

    Keyed by the container's DHIS2 UID - a data set UID for an aggregate form, a program UID for an
    event program and for every stage of a tracker program. A container absent from the index was
    not read, which is not the same as a container assigned to nothing: an absent container emits
    no artifact, an empty one emits a List no organisation unit is on.
    """

    model_config = ConfigDict(frozen=True)

    organisation_units: dict[str, frozenset[str]] = Field(default_factory=dict)

    def assigned(self, container_uid: str) -> frozenset[str] | None:
        """The units one container is assigned to, or None when the container was not read."""
        return self.organisation_units.get(container_uid)


class AssignmentContainer(BaseModel):
    """The DHIS2 object one form's assignment hangs on, with the identity its List artifact rides."""

    model_config = ConfigDict(frozen=True)

    uid: str
    name: str
    kind: AssignmentContainerKind
    stem: str
    """The identity stem the container's artifacts derive from - the form's own, or its program's."""


class AssignmentPlan(BaseModel):
    """Which assignment List each form references, keyed by the container the assignment hangs on.

    A form whose container is absent publishes no artifact, and its Questionnaire carries no
    `D2OrganisationUnitAssignment` extension - the whole registry may report it.
    """

    model_config = ConfigDict(frozen=True)

    list_ids: dict[str, str] = Field(default_factory=dict)

    def list_id_for(self, source: QuestionnaireSourceIn) -> str | None:
        """The id of the List scoping one form, or None when the form publishes no assignment."""
        if not FORM_KIND_PROFILES[source.kind].assigned:
            return None
        return self.list_ids.get(assignment_container_uid(source))

    def reference_for(self, source: QuestionnaireSourceIn) -> str | None:
        """The literal `List/<id>` reference one form's assignment extension carries, or None."""
        list_id = self.list_id_for(source)
        return None if list_id is None else f"{ASSIGNMENT_LIST_RESOURCE_TYPE}/{list_id}"


class EmptyAssignmentSummary(BaseModel):
    """The published forms no organisation unit may report: their assignment List names none.

    Counted in forms rather than in the data sets and programs DHIS2 hangs the assignment on,
    because the form is what a capture client is refused at: every stage of a tracker program
    publishes a Questionnaire of its own and the whole program shares one List, so a run reporting
    containers reports a number no other command can be made to agree with.
    """

    model_config = ConfigDict(frozen=True)

    form_count: int
    """How many published Questionnaires carry an assignment no organisation unit is on."""

    containers: list[str]
    """The data sets and programs the assignment hangs on, as `name (uid)`, sorted."""

    max_level: int | None = None
    """The `[generate.organisation_units] max_level` in force, which is what usually narrows the registry."""


class AssignmentBuild(JsonBuild):
    """The assignment Lists one run publishes, plus the plan the questionnaire emitters reference them by."""

    plan: AssignmentPlan = Field(default_factory=AssignmentPlan)
    empty_assignments: EmptyAssignmentSummary | None = None
    """The forms no organisation unit may report, or None when every published form has somewhere to report from."""


def assignment_container_uid(source: QuestionnaireSourceIn) -> str:
    """The DHIS2 UID of the object one form's assignment hangs on - the stage's program, else the form."""
    return source.uid if source.kind != "tracker-event" else source_program(source).uid


#: The form kinds whose assignment hangs on the tracker program rather than on the form itself. A
#: registration form *is* its program, so it is in here for its stem rather than for its UID: both
#: tracker kinds have to resolve the one container through the program surface, or a run would name
#: one program's List twice under two stems.
_PROGRAM_CONTAINER_KINDS = frozenset({"tracker", "tracker-event"})


def admitted_organisation_unit_uids(
    source: QuestionnaireSourceIn,
    assignments: AssignmentIndex,
    published_organisation_unit_uids: frozenset[str],
) -> frozenset[str]:
    """The published organisation units one form may be captured at: its DHIS2 assignment, narrowed to the registry.

    The one rule both the examples target and the questionnaires target grade against, so the unit
    an example is placed at and the units a form is said to have are the same set. A form of a kind
    DHIS2 hangs no assignment on - a tracked entity type - is admitted everywhere the registry
    publishes, and a run publishing no registry at all is admitted wherever its assignment names.
    """
    if FORM_KIND_PROFILES[source.kind].assigned:
        assigned = assignments.assigned(assignment_container_uid(source)) or frozenset()
    else:
        assigned = published_organisation_unit_uids
    return assigned & published_organisation_unit_uids if published_organisation_unit_uids else assigned


def assignment_container_kind(kind: FormKind) -> AssignmentContainerKind:
    """Which DHIS2 object kind holds one form kind's assignment."""
    return "data-set" if kind == "aggregate" else "program"


def assignment_container(source: QuestionnaireSourceIn, stem_plan: QuestionnaireStemPlan) -> AssignmentContainer:
    """The assignment container of one form, resolved through the surface its identity stem lives on.

    A data set and an event program are their own container, so the stem is the form target's.
    Both tracker kinds resolve to the program, whose stem is the directory segment their files
    already nest under - which is what makes a program's registration form and every one of its
    stages share the one artifact DHIS2 hangs the assignment on.
    """
    if source.kind in _PROGRAM_CONTAINER_KINDS:
        program = source_program(source)
        return AssignmentContainer(
            uid=program.uid,
            name=program.name,
            kind="program",
            stem=stem_plan.programs.stem_for(program.uid),
        )
    return AssignmentContainer(
        uid=source.uid,
        name=source.name,
        kind=assignment_container_kind(source.kind),
        stem=stem_plan.targets.stem_for(source.uid),
    )


def build_assignment_artifacts(
    sources: list[QuestionnaireSourceIn],
    assignments: AssignmentIndex,
    config: GenerateConfig,
    *,
    published: StemResolution,
    stem_plan: QuestionnaireStemPlan,
) -> AssignmentBuild:
    """Build one assignment List per container whose assignment narrows the published registry.

    `published` is the registry selection's stem resolution: its keys are the units the run
    publishes a Location for, and its stems are the ids those Locations carry. The assignment is
    intersected with that set before it is judged, so a unit DHIS2 assigns but the registry does
    not publish can never make an assignment look narrower than it is.

    A container left with no member at all takes its forms with it: they publish, and no organisation unit may
    report them. That outcome is summarised on the build as well as noted, because the terminal says
    it out loud at the end of a run rather than filing it with the terminology notes.
    """
    naming = QuestionnaireNaming.from_naming(config.naming)
    published_uids = frozenset(published.stems)
    build = AssignmentBuild()
    list_ids: dict[str, str] = {}
    empty_container_uids: set[str] = set()
    empty_containers: list[str] = []
    for container in _containers(sources, stem_plan):
        assigned = assignments.assigned(container.uid)
        if assigned is None:
            continue
        members = assigned & published_uids
        if members == published_uids:
            continue
        list_id = _assignment_list_id(naming, container)
        list_ids[container.uid] = list_id
        build.artifacts.append(
            _json_artifact(list_id, _assignment_list(list_id, container, members, published, config))
        )
        if not members:
            empty_container_uids.add(container.uid)
            empty_containers.append(f"{container.name} ({container.uid})")
    build.plan = AssignmentPlan(list_ids=list_ids)
    if empty_containers:
        build.empty_assignments = EmptyAssignmentSummary(
            form_count=_forms_on(sources, empty_container_uids),
            containers=sorted(empty_containers),
            max_level=config.organisation_units.max_level,
        )
        build.notes.append(
            generate_note(GenerateNoteCategory.SELECTION_GAP, _empty_assignment_message(build.empty_assignments))
        )
    return build


def _forms_on(sources: list[QuestionnaireSourceIn], container_uids: set[str]) -> int:
    """How many published forms hang on one of these assignment containers - the unit the facade counts."""
    return sum(
        1
        for source in sources
        if FORM_KIND_PROFILES[source.kind].assigned and assignment_container_uid(source) in container_uids
    )


def _empty_assignment_message(summary: EmptyAssignmentSummary) -> str:
    """The note one run files about the forms no organisation unit may report, naming what narrowed the registry."""
    narrowed = (
        f"; `[generate.organisation_units] max_level = {summary.max_level}` is what narrows the registry"
        if summary.max_level is not None
        else ""
    )
    return (
        f"{summary.form_count} published form(s) are assigned to no organisation unit the registry publishes, "
        f"so their assignment List is empty and no organisation unit may report them{narrowed}. The assignment "
        f"hangs on: "
        f"{', '.join(summary.containers)}"
    )


def _containers(sources: list[QuestionnaireSourceIn], stem_plan: QuestionnaireStemPlan) -> list[AssignmentContainer]:
    """Every distinct assignment container of the run, in the order the forms first name it.

    A form of a kind DHIS2 hangs no assignment on contributes none: a tracked entity type is not
    scoped to organisation units, so every unit the registry publishes may register one and there
    is nothing to narrow.
    """
    containers: dict[str, AssignmentContainer] = {}
    for source in sources:
        if not FORM_KIND_PROFILES[source.kind].assigned:
            continue
        container = assignment_container(source, stem_plan)
        containers.setdefault(container.uid, container)
    return list(containers.values())


def _assignment_list_id(naming: QuestionnaireNaming, container: AssignmentContainer) -> str:
    """FHIR id of one container's assignment List (e.g. `d2-ds-BfMAe6Itzgt-org-units`)."""
    return naming.assignment_list_id(container.kind, container.stem, container.uid)


def _assignment_list(
    list_id: str,
    container: AssignmentContainer,
    members: frozenset[str],
    published: StemResolution,
    config: GenerateConfig,
) -> ResourceList:
    """One container's assignment as a snapshot List of the Locations its units are published as.

    Entries are ordered by the Location id they reference, so a regenerate of an unchanged
    assignment produces a byte-identical file whatever order DHIS2 returned the units in.
    """
    references = sorted(published.reference_for("Location", uid) for uid in members)
    return ResourceList(
        id=list_id,
        identifier=[
            Identifier(
                system=_container_identifier_system(container.kind, config),
                value=container.uid,
            )
        ],
        status="current",
        mode="snapshot",
        title=f"{container.name} - assigned organisation units",
        entry=[ListEntry(item=Reference(reference=reference)) for reference in references] or None,
    )


def _container_identifier_system(kind: AssignmentContainerKind, config: GenerateConfig) -> str:
    """The DHIS2 identifier system the container UID on the List is stated under."""
    profile = FORM_KIND_PROFILES["aggregate" if kind == "data-set" else "event"]
    return f"{config.identifier_system_base}/id/{profile.identifier_segment}"


def _json_artifact(list_id: str, resource: ResourceList) -> JsonArtifact:
    """Serialise one assignment List as the predefined-resource file the loader reads."""
    return JsonArtifact(
        relative_path=f"{ASSIGNMENT_DIRECTORY}/{ASSIGNMENT_LIST_RESOURCE_TYPE}-{list_id}.json",
        content=f"{resource.model_dump_json(exclude_none=True, by_alias=True, indent=2)}\n",
    )
