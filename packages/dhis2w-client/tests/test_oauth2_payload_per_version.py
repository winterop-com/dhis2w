"""Per-version OAuth2 client-registration payload shapes (BUGS.md #39)."""

from __future__ import annotations

import httpx
import respx
from dhis2w_client import BasicAuth
from dhis2w_client.v41.oauth2_payload import build_register_payload as build_v41
from dhis2w_client.v42.oauth2_payload import build_register_payload as build_v42
from dhis2w_client.v43.oauth2_payload import build_register_payload as build_v43
from dhis2w_core.oauth2_registration import register_oauth2_client


def _common_kwargs() -> dict[str, object]:
    """Test fixture for the payload-builder kwargs."""
    return {
        "client_id": "my-app",
        "client_secret_hash": "$2b$10$dummyhashforshapeonly",
        "redirect_uri": "http://localhost:8765",
        "scope": "ALL",
        "display_name": "My App",
        "client_settings_json": "{}",
        "token_settings_json": "{}",
    }


def test_v41_payload_uses_cid_not_client_id() -> None:
    """v41 schema names the property `cid`; payload must not carry `clientId`."""
    payload = build_v41(**_common_kwargs())  # type: ignore[arg-type]
    assert payload["cid"] == "my-app"
    assert "clientId" not in payload


def test_v42_payload_uses_client_id_not_cid() -> None:
    """v42 renamed the property to `clientId`; payload must not carry `cid`."""
    payload = build_v42(**_common_kwargs())  # type: ignore[arg-type]
    assert payload["clientId"] == "my-app"
    assert "cid" not in payload


def test_v43_payload_uses_client_id_not_cid() -> None:
    """v43 carries v42's shape; payload must not carry `cid`."""
    payload = build_v43(**_common_kwargs())  # type: ignore[arg-type]
    assert payload["clientId"] == "my-app"
    assert "cid" not in payload


def test_v41_emits_arrays_for_multivalued_fields() -> None:
    """v41 rejects strings on multi-valued fields with a Jackson error; it needs arrays (BUGS.md #39)."""
    payload = build_v41(**_common_kwargs())  # type: ignore[arg-type]
    for field in ("clientAuthenticationMethods", "authorizationGrantTypes", "redirectUris", "scopes"):
        assert isinstance(payload[field], list)


def test_v42_and_v43_emit_comma_separated_strings_for_multivalued_fields() -> None:
    """2.42.6 and 2.43.1 answer 201 to arrays and store nothing for them (BUGS.md #117); strings persist."""
    for builder in (build_v42, build_v43):
        payload = builder(**_common_kwargs())  # type: ignore[arg-type]
        assert payload["authorizationGrantTypes"] == "authorization_code,refresh_token"
        assert payload["clientAuthenticationMethods"] == "client_secret_basic,client_secret_post"
        assert payload["redirectUris"] == "http://localhost:8765"
        assert payload["scopes"] == "ALL"


@respx.mock
async def test_register_oauth2_client_dispatches_to_v41_builder_on_v41_server() -> None:
    """`register_oauth2_client` against a v41 server posts the `cid`-shaped payload."""
    respx.get("https://dhis2.example/").mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get("https://dhis2.example/api/system/info").mock(
        return_value=httpx.Response(200, json={"version": "2.41.0"})
    )
    register_route = respx.post("https://dhis2.example/api/oAuth2Clients").mock(
        return_value=httpx.Response(201, json={"response": {"uid": "OAUTH_UID"}})
    )
    creds = await register_oauth2_client(
        base_url="https://dhis2.example",
        admin_auth=BasicAuth(username="admin", password="district"),
        client_id="my-app",
        client_secret="my-secret",
    )
    assert creds.uid == "OAUTH_UID"
    body = register_route.calls.last.request.read()
    assert b'"cid"' in body
    assert b'"clientId"' not in body


@respx.mock
async def test_register_oauth2_client_dispatches_to_v42_builder_on_v42_server() -> None:
    """`register_oauth2_client` against a v42 server posts the `clientId`-shaped payload."""
    respx.get("https://dhis2.example/").mock(return_value=httpx.Response(200, text="<html></html>"))
    respx.get("https://dhis2.example/api/system/info").mock(
        return_value=httpx.Response(200, json={"version": "2.42.4"})
    )
    register_route = respx.post("https://dhis2.example/api/oAuth2Clients").mock(
        return_value=httpx.Response(201, json={"response": {"uid": "OAUTH_UID"}})
    )
    await register_oauth2_client(
        base_url="https://dhis2.example",
        admin_auth=BasicAuth(username="admin", password="district"),
        client_id="my-app",
        client_secret="my-secret",
    )
    body = register_route.calls.last.request.read()
    assert b'"clientId"' in body
    assert b'"cid"' not in body
