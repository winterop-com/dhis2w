"""Pytest fixtures for dhis2w-mcp tests — mirrors dhis2w-client's seeded-env loading."""

from __future__ import annotations

import os
from pathlib import Path

import httpx2
import pytest


def _load_seeded_environment(start: Path) -> dict[str, str]:
    """Snapshot the environment with `infra/home/credentials/.env.auth` merged in underneath it.

    The seeded credentials stay in this mapping instead of going into `os.environ`: `DHIS2_URL`
    and its credential pair are the highest-precedence layer of profile resolution, so leaving
    them in the process environment makes every profile-resolving test in the session resolve
    against the local stack instead of the profile its own fixture wrote. Tests that want the
    seeded stack take the fixtures below and `monkeypatch.setenv` it for themselves.
    """
    values = dict(os.environ)
    for parent in [start, *start.parents]:
        candidate = parent / "infra" / "home" / "credentials" / ".env.auth"
        if not candidate.exists():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values.setdefault(key.strip(), value.strip())
        break
    return values


_SEEDED_ENVIRONMENT = _load_seeded_environment(Path(__file__).resolve())


@pytest.fixture(scope="session")
def local_url() -> str:
    """Base URL of the local DHIS2 instance (defaults to seeded DHIS2_URL)."""
    return _SEEDED_ENVIRONMENT.get("DHIS2_URL", "http://localhost:8080").rstrip("/")


@pytest.fixture(scope="session")
def local_pat() -> str | None:
    """Seeded default PAT (or None if infra hasn't been seeded)."""
    return _SEEDED_ENVIRONMENT.get("DHIS2_PAT")


def _live_version_key(url: str, pat: str) -> str | None:
    """The `v4N` key of the DHIS2 major answering at `url`, or None when the server is unreachable."""
    try:
        response = httpx2.get(f"{url}/api/system/info", headers={"Authorization": f"ApiToken {pat}"}, timeout=10.0)
        response.raise_for_status()
        version = str(response.json().get("version", ""))
    except (httpx2.HTTPError, ValueError):
        return None
    parts = version.split(".")
    return f"v{parts[1]}" if len(parts) >= 2 and parts[1].isdigit() else None


@pytest.fixture(scope="session")
def live_version_key(local_url: str, local_pat: str | None) -> str | None:
    """The plugin-tree key of the running local stack, probed once per session; None without a stack."""
    return _live_version_key(local_url, local_pat) if local_pat else None


@pytest.fixture(autouse=True)
def _follow_live_server(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    _neutral_profile_environment: None,
    live_version_key: str | None,
) -> None:
    """Point a slow test's plugin tree at the running server's major, after the neutral environment is set."""
    if request.node.get_closest_marker("slow") is not None and live_version_key is not None:
        monkeypatch.setenv("DHIS2_VERSION", live_version_key)
