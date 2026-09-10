"""Turning a caller's `verify` value into something httpx2 accepts — shared across version trees.

Every client surface takes `verify: bool | str`: a boolean toggles certificate
verification, a string names a custom CA bundle on disk. httpx2 accepts the
booleans directly but warns (`HTTPXDeprecationWarning`) on every request when
handed a path, so the path is turned into an `ssl.SSLContext` here, once, before
it reaches httpx2.

The logic carries no version-specific behaviour, so it lives in one shared
module rather than being copied per version, exactly like `_streaming.py`.
"""

from __future__ import annotations

import ssl
from pathlib import Path

__all__ = ["resolve_verify"]


def resolve_verify(verify: bool | str) -> bool | ssl.SSLContext:
    """Return `verify` unchanged when it is a boolean, or an SSL context loading the named CA bundle.

    Args:
        verify: `True` / `False` to toggle certificate verification, or a path
            to a PEM CA bundle to trust instead of the system trust store.

    Returns:
        The boolean as given, or an `ssl.SSLContext` seeded with the bundle.

    Raises:
        FileNotFoundError: The named CA bundle does not exist.
        ValueError: The named path exists but holds no loadable certificate.
    """
    if isinstance(verify, bool):
        return verify
    bundle_path = Path(verify)
    if not bundle_path.exists():
        raise FileNotFoundError(f"CA bundle not found: {verify}")
    try:
        return ssl.create_default_context(cafile=str(bundle_path))
    except (ssl.SSLError, OSError) as exc:
        raise ValueError(f"CA bundle is not a readable PEM certificate file: {verify}") from exc
