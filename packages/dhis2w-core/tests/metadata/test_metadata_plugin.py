"""Unit tests for the metadata plugin."""

from __future__ import annotations

from dhis2w_core.v42.plugins.metadata import plugin
from dhis2w_core.v42.plugins.metadata.service import _attr_name


def test_plugin_descriptor() -> None:
    """Plugin descriptor."""
    contribution = plugin.contribute("v42")
    assert contribution.name == "metadata"
    assert contribution.description


def test_attr_name_camel_to_snake() -> None:
    """Attr name camel to snake."""
    assert _attr_name("dataElements") == "data_elements"
    assert _attr_name("organisationUnits") == "organisation_units"
    assert _attr_name("indicators") == "indicators"
