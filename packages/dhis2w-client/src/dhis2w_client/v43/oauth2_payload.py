"""OAuth2 client-registration wire payload, v43 shape.

DHIS2 v43 names the client-id property `clientId` (v41 still uses `cid`,
DHIS2_ISSUES.md #39). Multi-valued fields ship as comma-separated strings: 2.42.6
and 2.43.1 answer 201 to JSON arrays and store nothing for those fields,
after which the authorization server answers 500 for the client
(DHIS2_ISSUES.md #117). v41 is the tree that needs arrays.

From 2.43.2 the registration rules 2.44 has apply (DHIS2_ISSUES.md #134): a
client may register only the OpenID scopes (`openid`, `email`, `profile`,
`username`; `ALL` is refused), and a client must require PKCE. Earlier v43
patches recognise only the single scope `ALL`. `default_scope_for` picks the
scope a login requests from the server's version, and the builder registers
the matching client: the four OpenID scopes with PKCE required for `openid`,
or the scope `ALL` for `ALL`.
"""

from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_SCOPE = "openid"
LEGACY_SCOPE = "ALL"
REGISTERED_SCOPES = "openid,email,profile,username"
OPENID_SCOPES_SINCE: tuple[int, int, int] = (2, 43, 2)
_PROOF_KEY_SETTING = "settings.client.require-proof-key"
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")


def default_scope_for(raw_version: str) -> str:
    """Return the scope a login requests on a server reporting `raw_version` (`2.43.1` -> `ALL`)."""
    match = _VERSION_RE.match(raw_version)
    if match is None:
        return DEFAULT_SCOPE
    parsed = (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
    return LEGACY_SCOPE if parsed < OPENID_SCOPES_SINCE else DEFAULT_SCOPE


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
    """Build the `POST /api/oAuth2Clients` body in v43's wire shape.

    `scope` is the scope a login requests: `ALL` registers a client with the scope `ALL`
    (servers before 2.43.2); any subset of `REGISTERED_SCOPES` registers all four OpenID
    scopes with PKCE required (2.43.2 onward).
    """
    requested = {part for part in scope.replace(",", " ").split() if part}
    if requested == {LEGACY_SCOPE}:
        registered_scopes = LEGACY_SCOPE
        client_settings_out = client_settings_json
    elif requested <= set(REGISTERED_SCOPES.split(",")):
        registered_scopes = REGISTERED_SCOPES
        client_settings = json.loads(client_settings_json)
        client_settings[_PROOF_KEY_SETTING] = True
        client_settings_out = json.dumps(client_settings, separators=(",", ":"))
    else:
        raise ValueError(
            f"a v43 client requests either {LEGACY_SCOPE} (before 2.43.2) or a subset of {REGISTERED_SCOPES}; "
            f"got {scope!r}"
        )
    return {
        "name": display_name or client_id,
        "clientId": client_id,
        "clientSecret": client_secret_hash,
        "clientAuthenticationMethods": "client_secret_basic,client_secret_post",
        "authorizationGrantTypes": "authorization_code,refresh_token",
        "redirectUris": redirect_uri,
        "scopes": registered_scopes,
        "clientSettings": client_settings_out,
        "tokenSettings": token_settings_json,
    }
