"""Tests for `resolve_verify` and the TLS `verify` plumbing on `Dhis2Client`."""

from __future__ import annotations

import ssl
import warnings
from pathlib import Path

import pytest
from dhis2w_client import BasicAuth, Dhis2Client
from dhis2w_client._tls import resolve_verify


@pytest.mark.parametrize("value", [True, False])
def test_resolve_verify_passes_booleans_through(value: bool) -> None:
    """A boolean reaches httpx2 unchanged."""
    assert resolve_verify(value) is value


def test_resolve_verify_builds_ssl_context_from_bundle(ca_bundle_path: Path) -> None:
    """A CA-bundle path becomes an `ssl.SSLContext` loading that bundle."""
    context = resolve_verify(str(ca_bundle_path))
    assert isinstance(context, ssl.SSLContext)
    assert context.get_ca_certs()


def test_resolve_verify_rejects_a_missing_bundle(tmp_path: Path) -> None:
    """A path that does not exist fails loudly instead of silently trusting nothing."""
    missing = tmp_path / "absent-ca.pem"
    with pytest.raises(FileNotFoundError, match="CA bundle not found"):
        resolve_verify(str(missing))


def test_resolve_verify_rejects_a_file_that_is_not_a_certificate(tmp_path: Path) -> None:
    """A file holding no loadable certificate raises rather than reaching httpx2."""
    junk = tmp_path / "not-a-cert.pem"
    junk.write_text("this is not a certificate\n")
    with pytest.raises(ValueError, match="not a readable PEM certificate"):
        resolve_verify(str(junk))


async def test_client_with_ca_bundle_opens_without_a_deprecation_warning(ca_bundle_path: Path) -> None:
    """`Dhis2Client(verify=<path>)` opens its pool with no `HTTPXDeprecationWarning`.

    httpx2 warns on every request when handed a bundle path as a string, so the
    client resolves the path to an `ssl.SSLContext` before httpx2 sees it.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        client = Dhis2Client(
            "https://dhis2.example",
            auth=BasicAuth(username="a", password="b"),
            verify=str(ca_bundle_path),
            skip_version_probe=True,
        )
        try:
            await client.connect()
        finally:
            await client.close()


async def test_client_rejects_a_missing_ca_bundle_at_construction() -> None:
    """A bad `verify` path fails when the client is built, not on the first request."""
    with pytest.raises(FileNotFoundError):
        Dhis2Client(
            "https://dhis2.example",
            auth=BasicAuth(username="a", password="b"),
            verify="/nonexistent/dhis2w-ca.pem",
            skip_version_probe=True,
        )
