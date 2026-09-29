"""Sanity check: every workspace member is importable."""

import dhis2w_cli
import dhis2w_client
import dhis2w_core


def test_members_importable() -> None:
    """Members importable."""
    for module in (dhis2w_client, dhis2w_core, dhis2w_cli):
        assert module.__doc__
