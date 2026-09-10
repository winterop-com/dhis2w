"""Tests for the terminology service that talks to a remote FHIR terminology server."""

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
import respx

from dhis2w_fhir_engine.r4.terminology import (
    InMemoryTerminologyService,
    MemberOfRequest,
    SubsumesRequest,
    ValidateCodeRequest,
)
from dhis2w_fhir_engine.r4.terminology.service import FHIRTerminologyService

BASE_URL = "http://terminology.example.org/fhir"
GENDER_VALUE_SET = "http://hl7.org/fhir/ValueSet/administrative-gender"
GENDER_SYSTEM = "http://hl7.org/fhir/administrative-gender"
SNOMED = "http://snomed.info/sct"


def parameters(**named_values: Any) -> dict[str, Any]:
    """Build a FHIR Parameters resource from name/value pairs."""
    parameter: list[dict[str, Any]] = []
    for name, value in named_values.items():
        if isinstance(value, bool):
            parameter.append({"name": name, "valueBoolean": value})
        else:
            parameter.append({"name": name, "valueString": value})
    return {"resourceType": "Parameters", "parameter": parameter}


def requested_url(router: respx.MockRouter) -> str:
    """Read the URL of the last request the router saw."""
    return str(router.calls.last.request.url)


class TestClientLifetime:
    """Tests for the HTTP client the remote service holds."""

    def test_close_closes_the_client(self) -> None:
        service = FHIRTerminologyService(BASE_URL)

        service.close()

        assert service._client.is_closed

    def test_leaving_the_context_closes_the_client(self) -> None:
        with FHIRTerminologyService(BASE_URL) as service:
            assert not service._client.is_closed

        assert service._client.is_closed


class TestRequestConstruction:
    """Tests for the HTTP request the remote service builds."""

    def test_the_base_url_loses_its_trailing_slash(self) -> None:
        assert FHIRTerminologyService(f"{BASE_URL}/").base_url == BASE_URL

    def test_headers_default_to_empty(self) -> None:
        assert FHIRTerminologyService(BASE_URL).headers == {}

    def test_configured_headers_join_the_fhir_content_headers(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(json=parameters(result=True))
            service = FHIRTerminologyService(BASE_URL, headers={"Authorization": "Bearer token-123"})

            service.validate_code(ValidateCodeRequest(url=GENDER_VALUE_SET, code="male"))

            headers = router.calls.last.request.headers
            assert headers["content-type"] == "application/fhir+json"
            assert headers["accept"] == "application/fhir+json"
            assert headers["authorization"] == "Bearer token-123"

    def test_a_get_carries_no_body(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(json=parameters(result=True))
            service = FHIRTerminologyService(BASE_URL)

            service.validate_code(ValidateCodeRequest(url=GENDER_VALUE_SET, code="male", system=GENDER_SYSTEM))

            assert router.calls.last.request.method == "GET"
            assert router.calls.last.request.content == b""
            assert requested_url(router) == (
                f"{BASE_URL}/ValueSet/$validate-code?url={GENDER_VALUE_SET}&code=male&system={GENDER_SYSTEM}"
            )

    def test_a_post_carries_the_json_body(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.post("/ValueSet/$expand").respond(json={"resourceType": "Parameters"})
            service = FHIRTerminologyService(BASE_URL)

            result = service._make_request("POST", "/ValueSet/$expand", {"resourceType": "Parameters", "parameter": []})

            assert result == {"resourceType": "Parameters"}
            assert router.calls.last.request.method == "POST"
            assert requested_url(router) == f"{BASE_URL}/ValueSet/$expand"
            assert json.loads(router.calls.last.request.content.decode("utf-8")) == {
                "resourceType": "Parameters",
                "parameter": [],
            }

    def test_a_transport_failure_yields_no_payload(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet").mock(side_effect=httpx2.ConnectError("boom"))
            service = FHIRTerminologyService(BASE_URL)

            assert service._make_request("GET", "/ValueSet") is None

    def test_a_server_error_yields_no_payload(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet").respond(500)
            service = FHIRTerminologyService(BASE_URL)

            assert service._make_request("GET", "/ValueSet") is None

    def test_a_body_that_is_not_json_yields_no_payload(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet").respond(content=b"<html>gateway timeout</html>")
            service = FHIRTerminologyService(BASE_URL)

            assert service._make_request("GET", "/ValueSet") is None


class TestRemoteValidateCode:
    """Tests for $validate-code against a remote server."""

    def test_a_valid_code_carries_message_and_display(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(
                json=parameters(result=True, message="Code is valid", display="Male")
            )
            service = FHIRTerminologyService(BASE_URL)

            response = service.validate_code(ValidateCodeRequest(url=GENDER_VALUE_SET, code="male"))

            assert response.result is True
            assert response.message == "Code is valid"
            assert response.display == "Male"

    def test_an_invalid_code_carries_the_server_message(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(
                json=parameters(result=False, message="Unknown code 'wombat'")
            )
            service = FHIRTerminologyService(BASE_URL)

            response = service.validate_code(ValidateCodeRequest(url=GENDER_VALUE_SET, code="wombat"))

            assert response.result is False
            assert response.message == "Unknown code 'wombat'"
            assert response.display is None

    def test_parameters_without_a_result_read_as_invalid(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(
                json={"resourceType": "Parameters", "parameter": [{"name": "version"}]}
            )
            service = FHIRTerminologyService(BASE_URL)

            response = service.validate_code(ValidateCodeRequest(url=GENDER_VALUE_SET, code="male"))

            assert response.result is False
            assert response.message is None

    def test_an_empty_request_still_reaches_the_operation(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(json=parameters(result=False))
            service = FHIRTerminologyService(BASE_URL)

            response = service.validate_code(ValidateCodeRequest())

            assert response.result is False
            assert requested_url(router) == f"{BASE_URL}/ValueSet/$validate-code?"

    def test_an_unreachable_server_reports_the_contact_failure(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").mock(side_effect=httpx2.ConnectError("boom"))
            service = FHIRTerminologyService(BASE_URL)

            response = service.validate_code(ValidateCodeRequest(url=GENDER_VALUE_SET, code="male"))

            assert response.result is False
            assert response.message == "Failed to contact terminology server"

    def test_an_empty_json_body_reports_the_contact_failure(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(json={})
            service = FHIRTerminologyService(BASE_URL)

            response = service.validate_code(ValidateCodeRequest(url=GENDER_VALUE_SET, code="male"))

            assert response.result is False
            assert response.message == "Failed to contact terminology server"


class TestRemoteMemberOf:
    """Tests for the membership check against a remote server."""

    def test_a_member_echoes_the_request_identity(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(json=parameters(result=True))
            service = FHIRTerminologyService(BASE_URL)

            request = MemberOfRequest(code="male", system=GENDER_SYSTEM, valueSetUrl=GENDER_VALUE_SET)
            response = service.member_of(request)

            assert response.result is True
            assert response.code == "male"
            assert response.system == GENDER_SYSTEM
            assert response.valueSetUrl == GENDER_VALUE_SET
            assert requested_url(router).startswith(f"{BASE_URL}/ValueSet/$validate-code?url={GENDER_VALUE_SET}")

    def test_a_non_member_reads_false(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").respond(json=parameters(result=False))
            service = FHIRTerminologyService(BASE_URL)

            request = MemberOfRequest(code="wombat", system=GENDER_SYSTEM, valueSetUrl=GENDER_VALUE_SET)
            response = service.member_of(request)

            assert response.result is False
            assert response.code == "wombat"

    def test_an_unreachable_server_reads_as_not_a_member(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet/$validate-code").mock(side_effect=httpx2.ConnectError("boom"))
            service = FHIRTerminologyService(BASE_URL)

            request = MemberOfRequest(code="male", system=GENDER_SYSTEM, valueSetUrl=GENDER_VALUE_SET)
            response = service.member_of(request)

            assert response.result is False


class TestRemoteSubsumes:
    """Tests for $subsumes against a remote server."""

    @pytest.mark.parametrize("outcome", ["equivalent", "subsumes", "subsumed-by", "not-subsumed"])
    def test_the_server_outcome_is_returned(self, outcome: str) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/CodeSystem/$subsumes").respond(
                json={"resourceType": "Parameters", "parameter": [{"name": "outcome", "valueCode": outcome}]}
            )
            service = FHIRTerminologyService(BASE_URL)

            response = service.subsumes(SubsumesRequest(codeA="73211009", codeB="44054006", system=SNOMED))

            assert response.outcome == outcome

    def test_the_request_carries_both_codes_and_the_system(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/CodeSystem/$subsumes").respond(
                json={"resourceType": "Parameters", "parameter": [{"name": "outcome", "valueCode": "subsumes"}]}
            )
            service = FHIRTerminologyService(BASE_URL)

            service.subsumes(SubsumesRequest(codeA="73211009", codeB="44054006", system=SNOMED))

            assert requested_url(router) == (
                f"{BASE_URL}/CodeSystem/$subsumes?codeA=73211009&codeB=44054006&system={SNOMED}"
            )

    def test_a_version_joins_the_query(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/CodeSystem/$subsumes").respond(
                json={"resourceType": "Parameters", "parameter": [{"name": "outcome", "valueCode": "equivalent"}]}
            )
            service = FHIRTerminologyService(BASE_URL)

            service.subsumes(SubsumesRequest(codeA="73211009", codeB="73211009", system=SNOMED, version="20240301"))

            assert requested_url(router).endswith("&version=20240301")

    def test_an_outcome_defaults_to_not_subsumed_when_the_code_is_absent(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/CodeSystem/$subsumes").respond(
                json={"resourceType": "Parameters", "parameter": [{"name": "outcome"}]}
            )
            service = FHIRTerminologyService(BASE_URL)

            response = service.subsumes(SubsumesRequest(codeA="73211009", codeB="44054006", system=SNOMED))

            assert response.outcome == "not-subsumed"

    def test_parameters_without_an_outcome_read_as_not_subsumed(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/CodeSystem/$subsumes").respond(
                json={"resourceType": "Parameters", "parameter": [{"name": "message"}]}
            )
            service = FHIRTerminologyService(BASE_URL)

            response = service.subsumes(SubsumesRequest(codeA="73211009", codeB="44054006", system=SNOMED))

            assert response.outcome == "not-subsumed"

    def test_an_unreachable_server_reads_as_not_subsumed(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/CodeSystem/$subsumes").mock(side_effect=httpx2.ConnectError("boom"))
            service = FHIRTerminologyService(BASE_URL)

            response = service.subsumes(SubsumesRequest(codeA="73211009", codeB="44054006", system=SNOMED))

            assert response.outcome == "not-subsumed"


class TestRemoteGetValueSet:
    """Tests for reading a ValueSet off a remote server."""

    def test_the_first_bundle_entry_is_parsed(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet").respond(
                json={
                    "resourceType": "Bundle",
                    "entry": [
                        {
                            "resource": {
                                "resourceType": "ValueSet",
                                "id": "administrative-gender",
                                "url": GENDER_VALUE_SET,
                                "version": "4.0.1",
                                "name": "AdministrativeGender",
                                "expansion": {
                                    "contains": [{"system": GENDER_SYSTEM, "code": "male", "display": "Male"}]
                                },
                            }
                        }
                    ],
                }
            )
            service = FHIRTerminologyService(BASE_URL)

            value_set = service.get_value_set(GENDER_VALUE_SET)

            assert value_set is not None
            assert value_set.name == "AdministrativeGender"
            assert value_set.expansion is not None
            assert [contained.code for contained in value_set.expansion.contains] == ["male"]
            assert requested_url(router) == f"{BASE_URL}/ValueSet?url={GENDER_VALUE_SET}"

    def test_a_version_joins_the_query(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet").respond(
                json={"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "ValueSet", "id": "vs"}}]}
            )
            service = FHIRTerminologyService(BASE_URL)

            value_set = service.get_value_set(GENDER_VALUE_SET, version="4.0.1")

            assert value_set is not None
            assert value_set.id == "vs"
            assert requested_url(router) == f"{BASE_URL}/ValueSet?url={GENDER_VALUE_SET}&version=4.0.1"

    def test_an_empty_bundle_yields_nothing(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet").respond(json={"resourceType": "Bundle", "entry": []})
            service = FHIRTerminologyService(BASE_URL)

            assert service.get_value_set(GENDER_VALUE_SET) is None

    def test_an_entry_without_a_resource_yields_nothing(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet").respond(json={"resourceType": "Bundle", "entry": [{"search": {"mode": "match"}}]})
            service = FHIRTerminologyService(BASE_URL)

            assert service.get_value_set(GENDER_VALUE_SET) is None

    def test_an_unreachable_server_yields_nothing(self) -> None:
        with respx.mock(base_url=BASE_URL) as router:
            router.get("/ValueSet").mock(side_effect=httpx2.ConnectError("boom"))
            service = FHIRTerminologyService(BASE_URL)

            assert service.get_value_set(GENDER_VALUE_SET) is None


class TestValueSetDirectoryLoading:
    """Tests for loading value sets off disk into the in-memory service."""

    def test_an_unparsable_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "gender.json").write_text(
            json.dumps({"resourceType": "ValueSet", "url": GENDER_VALUE_SET, "name": "AdministrativeGender"}),
            encoding="utf-8",
        )
        (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
        service = InMemoryTerminologyService()

        loaded = service.load_value_sets_from_directory(tmp_path)

        assert loaded == 1
        assert service.get_value_set(GENDER_VALUE_SET) is not None

    def test_a_missing_directory_loads_nothing(self, tmp_path: Path) -> None:
        service = InMemoryTerminologyService()

        assert service.load_value_sets_from_directory(tmp_path / "absent") == 0
