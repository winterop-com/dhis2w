"""OAuth2 client-registration wire payload, v44 shape.

DHIS2 v44 names the client-id property `clientId` (v41 still uses `cid`,
DHIS2_ISSUES.md #39). Multi-valued fields ship as comma-separated strings: 2.42.6
and 2.43.1 answer 201 to JSON arrays and store nothing for those fields,
after which the authorization server answers 500 for the client
(DHIS2_ISSUES.md #117). v41 is the tree that needs arrays.

2.44 adds two registration rules (DHIS2_ISSUES.md #134): a client may register only
the OpenID scopes (`openid`, `email`, `profile`, `username`; `ALL` is
refused), and a client must require PKCE. So this builder always registers
those four scopes and always sets `settings.client.require-proof-key`, and a
login requests `openid` (`DEFAULT_SCOPE`).
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_SCOPE = "openid"
REGISTERED_SCOPES = "openid,email,profile,username"
_PROOF_KEY_SETTING = "settings.client.require-proof-key"


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
    """Build the `POST /api/oAuth2Clients` body in v44's wire shape.

    `scope` is the scope a login requests; it must be one of `REGISTERED_SCOPES`, which
    the client registers whatever `scope` says.
    """
    requested = {part for part in scope.replace(",", " ").split() if part}
    allowed = set(REGISTERED_SCOPES.split(","))
    if not requested <= allowed:
        raise ValueError(f"DHIS2 2.44 allows only the scopes {REGISTERED_SCOPES}; got {scope!r}")
    client_settings = json.loads(client_settings_json)
    client_settings[_PROOF_KEY_SETTING] = True
    return {
        "name": display_name or client_id,
        "clientId": client_id,
        "clientSecret": client_secret_hash,
        "clientAuthenticationMethods": "client_secret_basic,client_secret_post",
        "authorizationGrantTypes": "authorization_code,refresh_token",
        "redirectUris": redirect_uri,
        "scopes": REGISTERED_SCOPES,
        "clientSettings": json.dumps(client_settings, separators=(",", ":")),
        "tokenSettings": token_settings_json,
    }
