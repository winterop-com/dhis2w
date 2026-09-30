"""Unit tests for the local `/api/schemas` manifest patches."""

from __future__ import annotations

from dhis2w_codegen.discover import Schema, SchemaProperty, SchemasManifest
from dhis2w_codegen.schema_patches import apply_schema_patches

_KLASS = "org.hisp.dhis.analytics.AggregationType"


def _manifest(category_option_property: SchemaProperty) -> SchemasManifest:
    """Build a manifest holding `dataElement` and one variant of `categoryOption.aggregationType`."""
    data_element_property = SchemaProperty(
        name="aggregationType", propertyType="CONSTANT", klass=_KLASS, constants=["SUM", "AVERAGE"]
    )
    return SchemasManifest(
        raw_version="2.43.1",
        version_key="v43",
        schemas=[
            Schema(
                name="dataElement", klass="org.hisp.dhis.dataelement.DataElement", properties=[data_element_property]
            ),
            Schema(
                name="categoryOption",
                klass="org.hisp.dhis.category.CategoryOption",
                properties=[category_option_property],
            ),
        ],
    )


def _aggregation_type(manifest: SchemasManifest) -> SchemaProperty:
    """Return `categoryOption.aggregationType` from `manifest`."""
    schema = next(schema for schema in manifest.schemas if schema.name == "categoryOption")
    return next(prop for prop in schema.properties if prop.name == "aggregationType")


def test_boolean_boot_is_pinned_to_the_enum() -> None:
    """A boot reporting BOOLEAN emits the same enum-typed property as a boot reporting CONSTANT (BUGS.md #95)."""
    boolean_boot = _manifest(
        SchemaProperty(name="aggregationType", propertyType="BOOLEAN", klass="java.lang.Boolean", writable=False)
    )

    pinned = _aggregation_type(apply_schema_patches(boolean_boot))

    assert pinned.propertyType == "CONSTANT"
    assert pinned.klass == _KLASS
    assert pinned.constants == ["SUM", "AVERAGE"]
    assert pinned.writable is True


def test_manifest_on_disk_is_left_as_reported() -> None:
    """Patching works on a copy; the input manifest keeps what the server reported."""
    boolean_boot = _manifest(SchemaProperty(name="aggregationType", propertyType="BOOLEAN", klass="java.lang.Boolean"))

    apply_schema_patches(boolean_boot)

    assert _aggregation_type(boolean_boot).propertyType == "BOOLEAN"
