"""The library half of the identity dial: reading one person's nominated values, and checking the nomination.

The register is the first consumer and not the only one intended: a summary document reads a person
the same way, so the reading lives here rather than in the server. `docs/fhir/design/ips.md`
section 4.
"""

from __future__ import annotations

import pytest
from dhis2w_fhir.ips import (
    ADMINISTRATIVE_GENDER_CODES,
    DATA_ABSENT_ERROR,
    DATA_ABSENT_UNKNOWN,
    AddressNominations,
    IdentityNominations,
    nominated_value_type_issues,
    served_identity,
)
from dhis2w_fhir.r4 import DATA_ABSENT_REASON_EXTENSION_URL

_NAME_ATTRIBUTE = "w75KJ2mc4zz"
_BIRTH_DATE_ATTRIBUTE = "iESIqZ0R0R0"
_SEX_ATTRIBUTE = "cejWyOfXge6"

_NOMINATIONS = IdentityNominations(
    name=_NAME_ATTRIBUTE,
    birth_date=_BIRTH_DATE_ATTRIBUTE,
    sex=_SEX_ATTRIBUTE,
    administrative_gender={"Male": "male", "Female": "female"},
)


def _absence_code(nominations: IdentityNominations, values: dict[str, str]) -> str | None:
    """The data-absent-reason one reading states on `_birthDate`, or None where it states none."""
    element = served_identity(values, nominations).birth_date_element
    if element is None or element.extension is None:
        return None
    return next(
        extension.valueCode for extension in element.extension if extension.url == DATA_ABSENT_REASON_EXTENSION_URL
    )


def test_the_four_administrative_gender_codes_are_the_whole_binding() -> None:
    """The binding is required, so the set a nomination may map onto is closed and stated once."""
    assert ADMINISTRATIVE_GENDER_CODES == ("male", "female", "other", "unknown")


def test_a_nominated_reading_fills_the_three_elements() -> None:
    """A name is a nomination or it is nothing, and this is what a nomination reads."""
    identity = served_identity(
        {_NAME_ATTRIBUTE: "Anna Nkemelu", _BIRTH_DATE_ATTRIBUTE: "2001-02-03", _SEX_ATTRIBUTE: "Female"},
        _NOMINATIONS,
    )

    assert identity.name is not None
    assert [name.text for name in identity.name] == ["Anna Nkemelu"]
    assert identity.birth_date == "2001-02-03"
    assert identity.gender == "female"
    assert identity.birth_date_element is None


def test_a_name_of_whitespace_alone_is_nothing_stated() -> None:
    """DHIS2 accepts a value of three spaces, and a name of three spaces is not one anybody can read."""
    assert served_identity({_NAME_ATTRIBUTE: "   "}, _NOMINATIONS).name is None


def test_a_name_keeps_its_own_spelling_and_loses_only_its_edges() -> None:
    """The value is the instance's, so nothing is capitalised, reordered, or split into halves."""
    identity = served_identity({_NAME_ATTRIBUTE: "  de la Cruz, María  "}, _NOMINATIONS)

    assert identity.name is not None
    assert identity.name[0].text == "de la Cruz, María"
    assert identity.name[0].family is None
    assert identity.name[0].given is None


def test_a_missing_birth_date_states_unknown_and_an_unreadable_one_states_error() -> None:
    """An instance-wide nomination is a statement about the attribute, not a promise about every row."""
    assert _absence_code(_NOMINATIONS, {}) == DATA_ABSENT_UNKNOWN
    assert _absence_code(_NOMINATIONS, {_BIRTH_DATE_ATTRIBUTE: "circa 2001"}) == DATA_ABSENT_ERROR


def test_a_project_nominating_no_birth_date_states_no_absence() -> None:
    """An element nobody asked for is not an element with something missing."""
    assert _absence_code(IdentityNominations(name=_NAME_ATTRIBUTE), {}) is None


def test_a_reading_over_no_nominations_states_nothing_at_all() -> None:
    """The default table is what every project written before it said, and it fills no element."""
    identity = served_identity({_NAME_ATTRIBUTE: "Anna Nkemelu"}, IdentityNominations())

    assert identity.name is None
    assert identity.gender is None
    assert identity.birth_date is None
    assert identity.birth_date_element is None


def test_a_value_type_the_element_cannot_take_is_an_issue_naming_the_key() -> None:
    """The refusal names the key, the attribute, and the type it found - not just that something is wrong."""
    issues = nominated_value_type_issues(
        _NOMINATIONS,
        {_NAME_ATTRIBUTE: "TEXT", _BIRTH_DATE_ATTRIBUTE: "INTEGER_POSITIVE", _SEX_ATTRIBUTE: "TEXT"},
    )

    assert [issue.key for issue in issues] == ["birth_date"]
    message = issues[0].message()
    assert _BIRTH_DATE_ATTRIBUTE in message
    assert "INTEGER_POSITIVE" in message
    assert "DATE" in message


def test_an_attribute_the_guide_publishes_nothing_about_raises_no_issue() -> None:
    """The guide's silence means the attribute is outside this project's selection, not that it is wrong."""
    assert nominated_value_type_issues(_NOMINATIONS, {}) == []


def test_a_long_text_attribute_may_carry_a_name() -> None:
    """DHIS2 spells a free-text attribute three ways, and a person's name arrives in any of them."""
    assert nominated_value_type_issues(IdentityNominations(name=_NAME_ATTRIBUTE), {_NAME_ATTRIBUTE: "LONG_TEXT"}) == []


_GIVEN_ATTRIBUTE = "TeaGivenNm1"
_FAMILY_ATTRIBUTE = "TeaFamilyN1"
_PHONE_ATTRIBUTE = "TeaMobile01"
_PROVINCE_ATTRIBUTE = "TeaProvinc1"
_DISTRICT_ATTRIBUTE = "TeaDistrct1"
_VILLAGE_ATTRIBUTE = "TeaVillage1"
_LINE_ATTRIBUTE = "TeaAddrLin1"
_PROVINCE_UNIT = "ProvUnit001"
_DISTRICT_UNIT = "DistUnit001"
_VILLAGE_UNIT = "VillUnit001"


def test_given_and_family_names_fill_one_human_name_beside_the_text() -> None:
    """Each half is nominated by the key that says which half it is, and all three land on one name."""
    nominations = IdentityNominations(name=_NAME_ATTRIBUTE, given_name=_GIVEN_ATTRIBUTE, family_name=_FAMILY_ATTRIBUTE)

    identity = served_identity(
        {_NAME_ATTRIBUTE: "Anna Nkemelu", _GIVEN_ATTRIBUTE: " Anna ", _FAMILY_ATTRIBUTE: "Nkemelu"}, nominations
    )

    assert identity.name is not None
    assert [name.model_dump(exclude_none=True) for name in identity.name] == [
        {"text": "Anna Nkemelu", "family": "Nkemelu", "given": ["Anna"]}
    ]


def test_a_given_name_alone_is_a_name() -> None:
    """`ips-pat-1` asks for family, given, or text, so one half is enough to publish."""
    identity = served_identity({_GIVEN_ATTRIBUTE: "Anna"}, IdentityNominations(given_name=_GIVEN_ATTRIBUTE))

    assert identity.name is not None
    assert [name.model_dump(exclude_none=True) for name in identity.name] == [{"given": ["Anna"]}]


def test_a_phone_attribute_is_one_phone_contact_point() -> None:
    """The nominated phone rides `telecom` as a phone, and a person holding none gets no entry."""
    nominations = IdentityNominations(phone=_PHONE_ATTRIBUTE)

    identity = served_identity({_PHONE_ATTRIBUTE: " 020 5555 1234 "}, nominations)

    assert identity.telecom is not None
    assert [point.model_dump(exclude_none=True) for point in identity.telecom] == [
        {"system": "phone", "value": "020 5555 1234"}
    ]
    assert served_identity({}, nominations).telecom is None


def _address_nominations() -> IdentityNominations:
    """A province, district and village picked from the hierarchy, plus a free-text line."""
    return IdentityNominations(
        address=AddressNominations(
            state=_PROVINCE_ATTRIBUTE, district=_DISTRICT_ATTRIBUTE, city=_VILLAGE_ATTRIBUTE, line=_LINE_ATTRIBUTE
        )
    )


def test_organisation_unit_address_parts_read_as_the_units_published_names() -> None:
    """A part holding a unit UID publishes the unit's name, and a text part publishes its text."""
    identity = served_identity(
        {
            _PROVINCE_ATTRIBUTE: _PROVINCE_UNIT,
            _DISTRICT_ATTRIBUTE: _DISTRICT_UNIT,
            _VILLAGE_ATTRIBUTE: _VILLAGE_UNIT,
            _LINE_ATTRIBUTE: "Unit 4",
        },
        _address_nominations(),
        organisation_unit_names={
            _PROVINCE_UNIT: "Western Area",
            _DISTRICT_UNIT: "Freetown",
            _VILLAGE_UNIT: "Kroo Bay",
        },
        organisation_unit_attributes=(_PROVINCE_ATTRIBUTE, _DISTRICT_ATTRIBUTE, _VILLAGE_ATTRIBUTE),
    )

    assert identity.address is not None
    assert [address.model_dump(exclude_none=True) for address in identity.address] == [
        {"line": ["Unit 4"], "city": "Kroo Bay", "district": "Freetown", "state": "Western Area"}
    ]


def test_a_unit_the_guide_publishes_nothing_about_leaves_its_part_out() -> None:
    """A UID in `Address.city` reads as nobody's village, so an unpublished unit fills no part."""
    identity = served_identity(
        {_PROVINCE_ATTRIBUTE: _PROVINCE_UNIT, _VILLAGE_ATTRIBUTE: _VILLAGE_UNIT},
        _address_nominations(),
        organisation_unit_names={_PROVINCE_UNIT: "Western Area"},
        organisation_unit_attributes=(_PROVINCE_ATTRIBUTE, _VILLAGE_ATTRIBUTE),
    )

    assert identity.address is not None
    assert [address.model_dump(exclude_none=True) for address in identity.address] == [{"state": "Western Area"}]


def test_an_address_with_no_part_read_is_no_address() -> None:
    """A person whose every part is empty or unreadable carries no `Address` at all."""
    identity = served_identity(
        {_VILLAGE_ATTRIBUTE: _VILLAGE_UNIT},
        _address_nominations(),
        organisation_unit_attributes=(_VILLAGE_ATTRIBUTE,),
    )

    assert identity.address is None


def test_the_new_keys_are_checked_against_their_value_types() -> None:
    """A phone must be a phone or text, and an address part a unit or text; each refusal names its key."""
    nominations = IdentityNominations(
        given_name=_GIVEN_ATTRIBUTE,
        phone=_PHONE_ATTRIBUTE,
        address=AddressNominations(state=_PROVINCE_ATTRIBUTE, city=_VILLAGE_ATTRIBUTE),
    )

    issues = nominated_value_type_issues(
        nominations,
        {
            _GIVEN_ATTRIBUTE: "TEXT",
            _PHONE_ATTRIBUTE: "NUMBER",
            _PROVINCE_ATTRIBUTE: "ORGANISATION_UNIT",
            _VILLAGE_ATTRIBUTE: "DATE",
        },
    )

    assert [issue.key for issue in issues] == ["phone", "address.city"]
    assert nominations.nominated_attribute_uids() == (
        _GIVEN_ATTRIBUTE,
        _PHONE_ATTRIBUTE,
        _VILLAGE_ATTRIBUTE,
        _PROVINCE_ATTRIBUTE,
    )


def test_an_address_part_is_nominated_by_uid() -> None:
    """A part named by an attribute's name nominates nothing, so the file refuses it."""
    with pytest.raises(ValueError, match="not a DHIS2 UID"):
        AddressNominations(city="Village")
