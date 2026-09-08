"""OAuth2 client-registration wire payload, v43 shape.

DHIS2 v43 names the client-id property `clientId` (v41 still uses `cid`,
BUGS.md #39). Multi-valued fields ship as comma-separated strings: 2.42.6
and 2.43.1 answer 201 to JSON arrays and store nothing for those fields,
after which the authorization server answers 500 for the client
(BUGS.md #117). v41 is the tree that needs arrays.
"""

from __future__ import annotations

from typing import Any


def build_register_payload(
    *,
    client_id: str,
    client_secret_hash: str,
    redirect_uri: str,
    scope: str,
    display_name: str | None,
    client_settings_json: str,
    token_settings_json: str,
) -> dict[str, Any]:
    """Build the `POST /api/oAuth2Clients` body in v43's wire shape."""
    return {
        "name": display_name or client_id,
        "clientId": client_id,
        "clientSecret": client_secret_hash,
        "clientAuthenticationMethods": "client_secret_basic,client_secret_post",
        "authorizationGrantTypes": "authorization_code,refresh_token",
        "redirectUris": redirect_uri,
        "scopes": scope,
        "clientSettings": client_settings_json,
        "tokenSettings": token_settings_json,
    }
