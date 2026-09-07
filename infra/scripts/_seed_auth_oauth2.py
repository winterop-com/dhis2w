"""Standard OAuth2 client seeded by `seed_auth.py`. Edit to change the client config.

Deterministic values so tests and manual exploration can rely on them. Re-running
the seed overwrites the existing client (by clientId lookup) instead of creating
duplicates.
"""

from __future__ import annotations

import importlib
from typing import Any

import bcrypt  # injected via `uv run --with bcrypt` by infra/Makefile

OAUTH2_CLIENT_ID = "dhis2w-utils-local"
OAUTH2_CLIENT_SECRET = "dhis2w-utils-local-secret-do-not-use-in-prod"  # noqa: S105 — local only
OAUTH2_REDIRECT_URI = "http://localhost:8765"
OAUTH2_SCOPES = "ALL"  # DHIS2 only recognises the single scope `ALL`
OAUTH2_GRANT_TYPES = "authorization_code,refresh_token"
# Spring Authorization Server requires this field to know how the client presents
# its credentials at /oauth2/token. client_secret_basic = HTTP Basic; client_secret_post
# = secret in the POST body. Registering both gives clients flexibility.
OAUTH2_CLIENT_AUTH_METHODS = "client_secret_basic,client_secret_post"

# DHIS2 stores Spring Authorization Server ClientSettings / TokenSettings as Jackson-serialized
# JSON TEXT columns. Leaving them empty triggers `IllegalArgumentException: settings cannot be
# empty` inside `Dhis2OAuth2ClientServiceImpl.toObject` when Spring AS tries to rebuild a
# RegisteredClient for /oauth2/authorize. These default values match what DHIS2's built-in
# settings app (/apps/settings#/oauth2) writes when a client is created through the UI.
OAUTH2_CLIENT_SETTINGS_JSON = (
    '{"@class":"java.util.Collections$UnmodifiableMap",'
    '"settings.client.require-proof-key":false,'
    '"settings.client.require-authorization-consent":true}'
)
OAUTH2_TOKEN_SETTINGS_JSON = (
    '{"@class":"java.util.Collections$UnmodifiableMap",'
    '"settings.token.reuse-refresh-tokens":true,'
    '"settings.token.x509-certificate-bound-access-tokens":false,'
    '"settings.token.id-token-signature-algorithm":'
    '["org.springframework.security.oauth2.jose.jws.SignatureAlgorithm","RS256"],'
    '"settings.token.access-token-time-to-live":["java.time.Duration",300.000000000],'
    '"settings.token.access-token-format":'
    '{"@class":"org.springframework.security.oauth2.server.authorization.settings.OAuth2TokenFormat",'
    '"value":"self-contained"},'
    '"settings.token.refresh-token-time-to-live":["java.time.Duration",3600.000000000],'
    '"settings.token.authorization-code-time-to-live":["java.time.Duration",300.000000000],'
    '"settings.token.device-code-time-to-live":["java.time.Duration",300.000000000]}'
)


def _bcrypt_hash(plaintext: str) -> str:
    """Produce a BCrypt hash of `plaintext` compatible with DHIS2's BCryptPasswordEncoder."""
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")


def oauth2_payload(version_key: str = "v42") -> dict[str, Any]:
    """Return the `POST /api/oAuth2Clients` body for one DHIS2 major.

    Delegates to `dhis2w_client.v{N}.oauth2_payload.build_register_payload`, the
    builder that owns each major's wire shape (`cid` and arrays on v41,
    `clientId` and comma-separated strings on v42 and v43; BUGS.md #39, #117).
    `clientSecret` is BCrypt-hashed because DHIS2 wires a `BCryptPasswordEncoder`
    into Spring Authorization Server's client authentication filter, so a
    plaintext value would always fail the `/oauth2/token` credential check.
    """
    payload_module = importlib.import_module(f"dhis2w_client.{version_key}.oauth2_payload")
    body: dict[str, Any] = payload_module.build_register_payload(
        client_id=OAUTH2_CLIENT_ID,
        client_secret_hash=_bcrypt_hash(OAUTH2_CLIENT_SECRET),
        redirect_uri=OAUTH2_REDIRECT_URI,
        scope=OAUTH2_SCOPES,
        display_name=OAUTH2_CLIENT_ID,
        client_settings_json=OAUTH2_CLIENT_SETTINGS_JSON,
        token_settings_json=OAUTH2_TOKEN_SETTINGS_JSON,
    )
    return body
