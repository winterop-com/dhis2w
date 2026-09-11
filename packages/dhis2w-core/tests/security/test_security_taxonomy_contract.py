"""Contract test: every taxonomy authority string exists in the live inventory.

The dangerous-authority taxonomy in `dhis2w_core.security_core.authorities`
hardcodes authority names. A name the running DHIS2 version does not define
can never be granted by current-version role editing and most likely gates
nothing -- matching on it gives false confidence. This test pins every
taxonomy string to the live `/api/authorities` inventory on the play
instances for v41, v42 and v43, minus the strings a major is known not to
define (`ABSENT_BY_VERSION`), each of which carries the live evidence.

Whether `/api/authorities` answers at all is a property of the
deployment, not of the major: some instances answer 500 on that route
while another instance on the identical revision answers 200 (BUGS.md
#45). A 500 therefore skips with a message naming that entry rather
than failing the run.

Marked `@pytest.mark.contract` so it runs in the dedicated CI job
(`.github/workflows/contract.yml`) and not as part of `make test`. Play
being unreachable or down (gateway 502/503/504) skips rather than fails.
"""

from __future__ import annotations

import httpx2
import pytest
from dhis2w_core.security_core import AUTHORITY_CATEGORIES

PLAY_URLS = {
    "v41": "https://play.im.dhis2.org/dev-2-41",
    "v42": "https://play.im.dhis2.org/dev-2-42",
    "v43": "https://play.im.dhis2.org/dev-2-43",
}

TAXONOMY_STRINGS: frozenset[str] = frozenset().union(*(category.authorities for category in AUTHORITY_CATEGORIES))

#: Taxonomy strings a major does not define, verified against the live inventory. `F_MOBILE_SETTINGS`
#: exists on 2.42.6 and 2.43.1 and on neither 2.41.10 nor the 2.41 dev channel (218 and 231
#: authorities listed, none of them mobile settings), so on v41 it can never be granted and the
#: category matches on its other three strings alone.
ABSENT_BY_VERSION: dict[str, frozenset[str]] = {"v41": frozenset({"F_MOBILE_SETTINGS"})}

_OUTAGE_STATUS_CODES = frozenset({502, 503, 504})


async def _fetch_inventory(base_url: str) -> set[str]:
    """Return the authority id inventory from a live instance, skipping only if it can't serve one.

    Network-level failures (`httpx2.RequestError`) and gateway outage statuses
    (502/503/504) skip. A 500 from `/api/authorities` skips too: the route is
    deployment-dependent, and an instance that refuses to enumerate its
    authorities cannot validate the taxonomy either way (BUGS.md #45). Every
    other HTTP error status fails the test — a 401 must not turn into a green
    run that validated nothing.
    """
    try:
        async with httpx2.AsyncClient(auth=("admin", "district"), timeout=30.0) as client:
            response = await client.get(f"{base_url}/api/authorities")
    except httpx2.RequestError as exc:
        pytest.skip(f"play instance {base_url} unreachable: {exc}")
    if response.status_code in _OUTAGE_STATUS_CODES:
        pytest.skip(f"play instance {base_url} down ({response.status_code})")
    if response.status_code == 500:
        pytest.skip(f"{base_url}/api/authorities answers 500 on this deployment (BUGS.md #45)")
    response.raise_for_status()
    body = response.json()
    return {entry["id"] for entry in body.get("systemAuthorities", [])}


@pytest.mark.contract
@pytest.mark.parametrize("version", sorted(PLAY_URLS))
async def test_taxonomy_strings_exist_in_live_inventory(version: str) -> None:
    """Every authority string in the taxonomy is defined by the live instance."""
    inventory = await _fetch_inventory(PLAY_URLS[version])
    assert inventory, f"{version}: live inventory came back empty"
    unknown = sorted(TAXONOMY_STRINGS - inventory - ABSENT_BY_VERSION.get(version, frozenset()))
    assert not unknown, f"{version}: taxonomy strings not in the live /api/authorities inventory: {unknown}"
