"""The `[ips]` tables: which attribute carries a person's identity, and which stage data is a dose.

`docs/fhir/design/ips.md` sections 4 and 5 are the argument in full, and they are one argument made
twice. DHIS2 has no name field, no sex field, and no date-of-birth field, and it marks no data
element as an immunisation, a problem, or an allergy. Which of an instance's tracked entity
attributes mean those demographic things, and which of its data elements belong in which section of
a patient summary, are decisions every instance makes for itself, usually differently. So both are
nominated or both are nothing, and this module holds the two nominations and the reading of them.

`[ips.identity]` fills `Patient.name`, `Patient.birthDate`, and `Patient.gender` on the register
projection, which is what section 9's phase 1 asked of it - before any summary document exists - and
`Patient.telecom` and `Patient.address` beside them, from a phone attribute and one attribute per
address part.
`[ips.sections]` says which recorded values a summary's clinical sections carry, and phase 2 maps
exactly one section: `Immunizations`. A section with no table is a section this project maps
nothing into, and the document states that rather than inventing content for it
(`dhis2w_fhir.summary`).

**Only UIDs, never names.** Attribute names are not unique in DHIS2 and change without notice, and
the guide already publishes the names it reads off the instance as `D2TEA_CS`.

**Honest failure per person, not per instance** (section 4, "Honest failure per person"). An
instance-wide nomination is a statement about the attribute, not a promise about every row: a person
the instance holds no birth date for keeps the required element and states its absence on the
data-absent-reason extension, which is the IG's own worked example. A person whose birth date is a
string this server cannot read as a date states the same absence under `error` rather than
`unknown`, because "nobody recorded one" and "what was recorded is not a date" are different
answers and a summary that flattened them would be less true than the instance is.

`name`, `gender`, `telecom`, and `address` state no absence, because none is a required element on
the resource the register serves: a `HumanName` carrying nothing but a data-absent extension
satisfies no reader and no invariant, and the other three are `0..1` or `0..*`. What the instance
holds is never lost either way - the raw attribute value rides the `D2TrackedEntityAttributeValue`
extension exactly as it always has, so a nomination adds a reading of a value and removes nothing.

**A place is read, not copied.** An address part nominated as an `ORGANISATION_UNIT` attribute holds
a unit's UID, and `Patient.address.district` wants the district's name. The name is the one the guide
itself publishes for that unit - its own Location, or its registry package's - so the address and the
`Location/<uid>` a client reads agree. A unit the guide publishes nothing about has no name here to
read, so that part is left out rather than filled with a UID nobody can read as a place.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dhis2w_fhir.names import is_dhis2_uid
from dhis2w_fhir.r4 import DATA_ABSENT_REASON_EXTENSION_URL, Address, ContactPoint, Element, Extension, HumanName

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

__all__ = [
    "ADMINISTRATIVE_GENDER_CODES",
    "ADMINISTRATIVE_GENDER_CODE_SYSTEM_URL",
    "ADMINISTRATIVE_GENDER_VALUE_SET_URL",
    "DATA_ABSENT_ERROR",
    "DATA_ABSENT_UNKNOWN",
    "NOMINATION_VALUE_TYPES",
    "ORGANISATION_UNIT_VALUE_TYPE",
    "AddressNominations",
    "AdministrativeGender",
    "IdentityNominations",
    "ImmunizationsMapping",
    "NominatedValueTypeIssue",
    "SectionMappings",
    "ServedIdentity",
    "nominated_value_type_issues",
    "served_identity",
]

#: R4's own gender vocabulary, which `Patient.gender` is bound to with a **required** binding - so a
#: DHIS2 option code reaches it through a map rather than through a rename (design/ips.md section 4).
ADMINISTRATIVE_GENDER_CODE_SYSTEM_URL = "http://hl7.org/fhir/administrative-gender"

#: The value set of that same vocabulary, which the published map names as its target.
ADMINISTRATIVE_GENDER_VALUE_SET_URL = "http://hl7.org/fhir/ValueSet/administrative-gender"

#: The four codes the required binding admits, and the whole of what a nomination may map onto.
ADMINISTRATIVE_GENDER_CODES: tuple[str, ...] = ("male", "female", "other", "unknown")

#: The `Patient.gender` element's type, spelled once so a served resource and a config refusal agree.
type AdministrativeGender = Literal["male", "female", "other", "unknown"]

#: What a required element states when the instance holds no value for the attribute nominated for it.
#: The IG's worked example is `Patient._birthDate` carrying exactly this code.
DATA_ABSENT_UNKNOWN = "unknown"

#: What it states when the instance holds a value this server cannot read as the element's datatype.
DATA_ABSENT_ERROR = "error"

#: The DHIS2 value types each nomination accepts, checked against `D2TEA_CS` at startup
#: (design/ips.md section 4, "Value-shape validation"). A `sex` attribute is checked as `TEXT`
#: alone: the guide publishes an attribute's value type and not the option set behind it, so
#: whether the text comes from a list is a fact the vocabulary does not carry. Every part of
#: `address` shares one row: a part is a place's name, typed in or read off an organisation unit.
NOMINATION_VALUE_TYPES: dict[str, tuple[str, ...]] = {
    "name": ("TEXT", "LONG_TEXT", "LETTER"),
    "given_name": ("TEXT", "LONG_TEXT", "LETTER"),
    "family_name": ("TEXT", "LONG_TEXT", "LETTER"),
    "birth_date": ("DATE",),
    "sex": ("TEXT",),
    "phone": ("PHONE_NUMBER", "TEXT"),
    "address": ("ORGANISATION_UNIT", "TEXT", "LONG_TEXT"),
}

#: The DHIS2 value type whose value is an organisation unit's UID rather than text to publish as is.
ORGANISATION_UNIT_VALUE_TYPE = "ORGANISATION_UNIT"


def _nominated_uid(value: str | None) -> str | None:
    """Every nomination names a DHIS2 object by UID - a name or a code here would nominate nothing."""
    if value is None:
        return value
    if not is_dhis2_uid(value):
        raise ValueError(
            f"{value!r} is not a DHIS2 UID (one letter followed by ten alphanumeric places): "
            "nominate the tracked entity attribute by its UID, since names and codes are not "
            "unique in DHIS2 and change without notice"
        )
    return value


class AddressNominations(BaseModel):
    """Which tracked entity attribute carries which part of a person's address - `[ips.identity.address]`.

    One attribute per part, because DHIS2 has no address field and an instance that records one keeps
    each part in an attribute of its own, usually an organisation unit picked from the hierarchy. The
    keys are R4's own `Address` parts, `postal_code` spelled the way this file spells every key.
    `line` fills the single entry of `Address.line`. Nothing here parses one string into parts: which
    part a value is, is what the key says.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    line: str | None = None
    city: str | None = None
    district: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None

    @field_validator("line", "city", "district", "state", "postal_code", "country")
    @classmethod
    def _dhis2_uid(cls, value: str | None) -> str | None:
        """Every part names a tracked entity attribute by UID."""
        return _nominated_uid(value)

    def parts(self) -> tuple[tuple[str, str], ...]:
        """Every nominated part as `(key, attribute uid)`, in R4's own order."""
        return tuple(
            (key, uid)
            for key, uid in (
                ("line", self.line),
                ("city", self.city),
                ("district", self.district),
                ("state", self.state),
                ("postal_code", self.postal_code),
                ("country", self.country),
            )
            if uid is not None
        )


class IdentityNominations(BaseModel):
    """Which tracked entity attribute carries which demographic fact - the `[ips.identity]` table.

    Attributes are nominated by UID, one per element, and one key states what a sex value means.
    `administrative_gender` maps the value DHIS2 stores against the `sex` attribute - the option's
    DHIS2 code on an option-set-bound attribute - onto one of R4's four `administrative-gender`
    codes. It is a map rather than a rename because the binding on `Patient.gender` is required, and
    it is the smallest possible instance of the clinical-vocabulary source `docs/fhir/design/ips.md`
    section 3 says does not exist yet: four codes rather than forty thousand.

    `name` publishes as `Patient.name[0].text`, `given_name` as `name[0].given`, and `family_name`
    as `name[0].family`, all on one `HumanName`. Any one of them satisfies the IPS invariant
    `ips-pat-1`, which asks for `family`, `given`, **or** `text`. An instance whose given and family
    names sit in two attributes nominates each by the key that says which half it is; nothing here
    splits one value into halves, and no key is guessed from an attribute's name.

    `phone` publishes as one `Patient.telecom` entry with system `phone`. `address` names one
    attribute per address part and publishes one `Patient.address` - see `AddressNominations`.

    An empty table nominates nothing, which is what every project that never wrote it states: the
    register serves the identity it always served, which is none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    """The tracked entity attribute whose value is published as `Patient.name[0].text`."""

    given_name: str | None = None
    """The tracked entity attribute whose value is published as `Patient.name[0].given[0]`."""

    family_name: str | None = None
    """The tracked entity attribute whose value is published as `Patient.name[0].family`."""

    birth_date: str | None = None
    """The tracked entity attribute whose value is published as `Patient.birthDate`."""

    sex: str | None = None
    """The tracked entity attribute whose value `administrative_gender` reads as `Patient.gender`."""

    phone: str | None = None
    """The tracked entity attribute whose value is published as a `Patient.telecom` phone number."""

    address: AddressNominations = Field(default_factory=AddressNominations)
    """One tracked entity attribute per part of `Patient.address`."""

    administrative_gender: dict[str, str] = Field(default_factory=dict)
    """One DHIS2 value of the `sex` attribute per key, mapped onto `male`, `female`, `other`, or `unknown`."""

    @field_validator("name", "given_name", "family_name", "birth_date", "sex", "phone")
    @classmethod
    def _dhis2_uid(cls, value: str | None) -> str | None:
        """Every nomination names a DHIS2 object by UID - a name or a code here would nominate nothing."""
        return _nominated_uid(value)

    @field_validator("administrative_gender")
    @classmethod
    def _administrative_gender_codes(cls, value: dict[str, str]) -> dict[str, str]:
        """`Patient.gender` takes four codes and no others, so a fifth word here would map onto nothing."""
        for dhis2_value, gender in value.items():
            if gender not in ADMINISTRATIVE_GENDER_CODES:
                raise ValueError(
                    f"the DHIS2 value {dhis2_value!r} is mapped to {gender!r}, which is not one of R4's "
                    f"administrative-gender codes: name one of {', '.join(ADMINISTRATIVE_GENDER_CODES)}"
                )
        return value

    @model_validator(mode="after")
    def _sex_and_its_map_arrive_together(self) -> IdentityNominations:
        """One without the other states a gender nobody can serve, so the file refuses the pair broken.

        A nominated `sex` with an empty map reads every person's value as unmapped and publishes no
        `gender` at all; a map with no `sex` names values of an attribute nobody nominated. Both
        parse and neither does anything, which is the failure mode `ServeAuth` keeps `oauth2` out of
        the enum to avoid.
        """
        if self.sex is not None and not self.administrative_gender:
            raise ValueError(
                "sex nominates a tracked entity attribute and [ips.identity.administrative_gender] maps "
                "nothing: state one line per value the attribute holds, mapped onto "
                f"{', '.join(ADMINISTRATIVE_GENDER_CODES)}"
            )
        if self.sex is None and self.administrative_gender:
            raise ValueError(
                "[ips.identity.administrative_gender] maps values of an attribute nobody nominated: "
                'state `sex = "<attribute uid>"` beside it, or drop the map'
            )
        return self

    def nominated_keys(self) -> tuple[tuple[str, str], ...]:
        """Every nomination as `(key, attribute uid)` in the order the keys are declared, parts as `address.<part>`."""
        own = (
            ("name", self.name),
            ("given_name", self.given_name),
            ("family_name", self.family_name),
            ("birth_date", self.birth_date),
            ("sex", self.sex),
            ("phone", self.phone),
        )
        stated = tuple((key, uid) for key, uid in own if uid is not None)
        return stated + tuple((f"address.{key}", uid) for key, uid in self.address.parts())

    def nominates_anything(self) -> bool:
        """Whether this table nominates a single attribute, which is what every caller asks first."""
        return bool(self.nominated_keys())

    def nominated_attribute_uids(self) -> tuple[str, ...]:
        """Every attribute this table nominates, once each, in the order the keys are declared."""
        return tuple(dict.fromkeys(uid for _, uid in self.nominated_keys()))


class ImmunizationsMapping(BaseModel):
    """Which recorded values are doses - the `[ips.sections.immunizations]` table.

    `docs/fhir/design/ips.md` section 6 puts the Immunizations row at `WITH A MAPPING` and says what
    the mapping has to state: dose events in an immunisation program stage, with the event's own date
    as the occurrence. This table states exactly that, in two lists.

    `program_stages` names the stages whose events record doses. `dose_data_elements` names the data
    elements inside them that each record a dose of one vaccine - which is the shape a DHIS2
    immunisation form actually has: `MCH BCG dose`, `MCH Measles dose`, `MCH Penta dose`, one element
    per vaccine, the value saying that a dose was given or which dose of the series it was. So **the
    data element is the vaccine and the value is the dose**, and `Immunization.vaccineCode` carries
    the data element's own DHIS2 coding. The IPS binds `vaccineCode` **preferably** rather than
    requiredly, so publishing a DHIS2 coding there violates no profile - which is what lets this
    section carry real doses while an international vaccine vocabulary is still missing (section 5).

    Both lists are required together. A stage with no data element nominated records nothing this
    reads, and a data element with no stage names values on events nobody said were doses; either
    alone maps nothing, which is the failure mode `[ips.identity]` refuses the same way.

    An empty table maps nothing, which is what every project that never wrote it states.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    program_stages: tuple[str, ...] = ()
    """The program stages whose events carry doses, by UID."""

    dose_data_elements: tuple[str, ...] = ()
    """The data elements inside those stages that each record a dose of one vaccine, by UID."""

    @field_validator("program_stages", "dose_data_elements")
    @classmethod
    def _dhis2_uids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Every nomination names a DHIS2 object by UID - a name or a code here would nominate nothing."""
        for stated in value:
            if not is_dhis2_uid(stated):
                raise ValueError(
                    f"{stated!r} is not a DHIS2 UID (one letter followed by ten alphanumeric places): "
                    "nominate the object by its UID, since names and codes are not unique in DHIS2 and "
                    "change without notice"
                )
        return value

    @model_validator(mode="after")
    def _stages_and_elements_arrive_together(self) -> ImmunizationsMapping:
        """One list without the other maps no dose at all, so the file refuses the pair broken."""
        if self.program_stages and not self.dose_data_elements:
            raise ValueError(
                "[ips.sections.immunizations] program_stages names a stage and dose_data_elements names "
                "no data element: state which of that stage's data elements each record a dose"
            )
        if self.dose_data_elements and not self.program_stages:
            raise ValueError(
                "[ips.sections.immunizations] dose_data_elements names a data element and program_stages "
                "names no stage: state which program stage's events those values are recorded on"
            )
        return self

    def maps_anything(self) -> bool:
        """Whether this table maps a single dose, which is what every caller asks first."""
        return bool(self.program_stages and self.dose_data_elements)

    def records_dose(self, program_stage_uid: str | None, data_element_uid: str) -> bool:
        """Whether one value of one stage's event is a dose this table nominated."""
        if program_stage_uid is None:
            return False
        return program_stage_uid in self.program_stages and data_element_uid in self.dose_data_elements


class SectionMappings(BaseModel):
    """Which recorded values belong in which section of a summary - the `[ips.sections]` tables.

    One sub-table per IPS section this project maps, and `immunizations` is the only one phase 2
    ships: `docs/fhir/design/ips.md` section 9 says why it goes first, and section 6 says why every
    other section needs its own nomination rather than a general rule. A section named here that this
    version does not map is refused by name, so a project writing `[ips.sections.problems]` today is
    told the key is not one rather than left with a table that quietly does nothing.

    An absent table maps no section at all. The summary is still served - the owner's call, and
    `dhis2w_fhir.summary` states the caveat that goes with it - with its three required sections
    carrying an empty reason and its recommended sections omitted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    immunizations: ImmunizationsMapping = Field(default_factory=ImmunizationsMapping)

    def maps_anything(self) -> bool:
        """Whether a single clinical section of a summary is mapped, which decides the document's caveat."""
        return self.immunizations.maps_anything()


class ServedIdentity(BaseModel):
    """The demographic elements one nomination fills on one person, and the absences it states.

    The field names are the FHIR element names on purpose: a caller carries this straight onto the
    resource it is serving, so what this decides and what a client reads cannot drift apart.
    """

    model_config = ConfigDict(frozen=True)

    name: list[HumanName] | None = None
    gender: AdministrativeGender | None = None
    birth_date: str | None = None
    birth_date_element: Element | None = None
    """The `_birthDate` sibling carrying the data-absent-reason extension, when the date is absent."""

    telecom: list[ContactPoint] | None = None
    address: list[Address] | None = None


class NominatedValueTypeIssue(BaseModel):
    """One nominated attribute whose published DHIS2 value type is not one the FHIR element accepts."""

    model_config = ConfigDict(frozen=True)

    key: str
    attribute_uid: str
    value_type: str
    accepted: tuple[str, ...]

    def message(self) -> str:
        """The refusal a run states, naming the key, the attribute, and the value type it found."""
        return (
            f"[ips.identity] {self.key} nominates tracked entity attribute {self.attribute_uid}, which this "
            f"guide publishes as DHIS2 value type {self.value_type}: the FHIR element it fills takes "
            f"{', '.join(self.accepted)}. Nominate an attribute of that type, or drop the key."
        )


def nominated_value_type_issues(
    nominations: IdentityNominations, value_types: Mapping[str, str]
) -> list[NominatedValueTypeIssue]:
    """Check every nomination against the value type `D2TEA_CS` publishes for it, in key order.

    `docs/fhir/design/ips.md` section 4, "Value-shape validation": a nomination whose value type
    cannot fill the element it was nominated for refuses the run, in the manner
    `[generate.tracked_entity_types]` refuses a resource type that is not one.

    An attribute the guide publishes nothing about raises no issue. The guide's silence is not
    evidence of a wrong type - it means the attribute is outside this project's selection - and
    `[serve.tracked_entities] search_attributes` already settles that an operator's nomination of an
    attribute outstates what the vocabulary happens to carry about it.
    """
    issues: list[NominatedValueTypeIssue] = []
    for key, attribute_uid in nominations.nominated_keys():
        accepted = NOMINATION_VALUE_TYPES[key.split(".", 1)[0]]
        value_type = value_types.get(attribute_uid)
        if value_type is None or value_type in accepted:
            continue
        issues.append(
            NominatedValueTypeIssue(key=key, attribute_uid=attribute_uid, value_type=value_type, accepted=accepted)
        )
    return issues


def served_identity(
    values: Mapping[str, str],
    nominations: IdentityNominations,
    *,
    organisation_unit_names: Mapping[str, str] | None = None,
    organisation_unit_attributes: Collection[str] = (),
) -> ServedIdentity:
    """Read one person's nominated attribute values as the demographic elements they were nominated for.

    `values` is that person's attribute values keyed by attribute UID. A nomination the person holds
    no value for, and a value this server cannot read, are both per-person facts rather than
    instance-wide ones - see this module's docstring for which of them states what.

    `organisation_unit_names` is every unit the guide publishes, by UID, and
    `organisation_unit_attributes` the attributes it publishes as `ORGANISATION_UNIT`: together they
    are how an address part holding a unit's UID is read as that unit's name.
    """
    return ServedIdentity(
        name=_served_name(
            _stated(values, nominations.name),
            _stated(values, nominations.given_name),
            _stated(values, nominations.family_name),
        ),
        gender=_served_gender(_stated(values, nominations.sex), nominations.administrative_gender),
        birth_date=_served_birth_date(_stated(values, nominations.birth_date)),
        birth_date_element=_birth_date_absence(nominations.birth_date, _stated(values, nominations.birth_date)),
        telecom=_served_telecom(_stated(values, nominations.phone)),
        address=_served_address(
            values, nominations.address, organisation_unit_names or {}, organisation_unit_attributes
        ),
    )


def _read_place(
    attribute_uid: str, value: str, unit_names: Mapping[str, str], unit_attributes: Collection[str]
) -> str | None:
    """One address part's value as the place it names: a unit's published name, the text itself, or None.

    A value naming a unit the guide publishes reads as that unit's name whatever the attribute's type,
    since an attribute outside the guide's vocabulary still holds UIDs if it holds units. A value of an
    attribute published as `ORGANISATION_UNIT` that names no published unit is left out: it is a UID,
    and a UID in `Address.district` reads as nobody's district. The names are read in place, never
    copied, because a national hierarchy is tens of thousands of them and a page serves fifty people.
    """
    name = unit_names.get(value)
    if name is not None:
        return name
    if attribute_uid in unit_attributes:
        return None
    return value


def _stated(values: Mapping[str, str], attribute_uid: str | None) -> str | None:
    """The value this person holds for one nominated attribute, or None where the nomination is empty.

    A value of whitespace alone is nothing stated: DHIS2 accepts one, and a name of three spaces is
    not a name a clinician can read.
    """
    if attribute_uid is None:
        return None
    value = values.get(attribute_uid)
    return None if value is None or not value.strip() else value


def _served_name(text: str | None, given: str | None, family: str | None) -> list[HumanName] | None:
    """The nominated name parts as one `HumanName`, or nothing where the person holds none of them."""
    if text is None and given is None and family is None:
        return None
    return [
        HumanName(
            text=None if text is None else text.strip(),
            family=None if family is None else family.strip(),
            given=None if given is None else [given.strip()],
        )
    ]


def _served_telecom(value: str | None) -> list[ContactPoint] | None:
    """The nominated phone attribute as one `phone` contact point, or nothing where the person holds none."""
    return None if value is None else [ContactPoint(system="phone", value=value.strip())]


def _served_address(
    values: Mapping[str, str],
    nominations: AddressNominations,
    unit_names: Mapping[str, str],
    unit_attributes: Collection[str],
) -> list[Address] | None:
    """The nominated address parts as one `Address`, or nothing where the person holds no part this reads."""
    parts: dict[str, str] = {}
    for key, attribute_uid in nominations.parts():
        value = _stated(values, attribute_uid)
        if value is None:
            continue
        place = _read_place(attribute_uid, value.strip(), unit_names, unit_attributes)
        if place is not None:
            parts[key] = place
    if not parts:
        return None
    line = parts.get("line")
    return [
        Address(
            line=None if line is None else [line],
            city=parts.get("city"),
            district=parts.get("district"),
            state=parts.get("state"),
            postalCode=parts.get("postal_code"),
            country=parts.get("country"),
        )
    ]


def _served_gender(value: str | None, administrative_gender: Mapping[str, str]) -> AdministrativeGender | None:
    """The nominated sex value as an `administrative-gender` code, or nothing where the map has no row.

    A value outside the map publishes no `gender`. The binding is required, so an unmapped value has
    no code to become; the value itself is still served on the attribute-value extension, so a client
    reading the person sees exactly what DHIS2 holds and this server states nothing it was not told.
    """
    if value is None:
        return None
    gender = administrative_gender.get(value.strip())
    return gender if gender in ADMINISTRATIVE_GENDER_CODES else None  # type: ignore[return-value]


def _served_birth_date(value: str | None) -> str | None:
    """The nominated birth date as a FHIR `date`, or nothing where the person holds none this reads."""
    return None if value is None else _read_date(value)


def _birth_date_absence(attribute_uid: str | None, value: str | None) -> Element | None:
    """The `_birthDate` sibling stating why the date is absent, or nothing where a date was served.

    Only a project that nominated a birth date states an absence: an element nobody asked for is not
    an element with something missing, which is what keeps a project with no `[ips.identity]` table
    serving byte-identically to one served before the table existed.
    """
    if attribute_uid is None:
        return None
    if value is not None and _read_date(value) is not None:
        return None
    reason = DATA_ABSENT_UNKNOWN if value is None else DATA_ABSENT_ERROR
    return Element(extension=[Extension(url=DATA_ABSENT_REASON_EXTENSION_URL, valueCode=reason)])


def _read_date(value: str) -> str | None:
    """One DHIS2 value as a FHIR `date`, or None where it is not a date at all.

    DHIS2 answers a `DATE` attribute as `2001-01-01` and sometimes as the midnight instant of that
    day, so the day is taken off the front of either. Anything else reads as no date: the raw value
    keeps riding the attribute-value extension, and the element states its absence rather than
    publishing a birth date the instance never recorded.
    """
    try:
        return date.fromisoformat(value.strip().split("T", 1)[0]).isoformat()
    except ValueError:
        return None
