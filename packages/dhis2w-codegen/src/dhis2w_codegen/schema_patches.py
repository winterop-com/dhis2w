"""Local patches applied to a `/api/schemas` manifest before emission.

The committed `schemas_manifest.json` stays exactly what the server reported; `emit()`
applies these patches to a copy, so the audit trail and the emitted models can differ
only where a patch says why.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from dhis2w_codegen.discover import Schema, SchemaProperty, SchemasManifest


class BootDependentProperty(BaseModel):
    """A property whose type changes between boots, pinned to the type of a stable sibling."""

    model_config = ConfigDict(frozen=True)

    schema_name: str
    property_name: str
    reference_schema_name: str
    writable: bool
    bugs_ref: str


# On 2.43.1 `categoryOption.aggregationType` reads `BOOLEAN` on some boots of one image and
# `CONSTANT` on others, the same member collision that moves the OpenAPI document (BUGS.md #95,
# #133). Reads omit the property on every category option; what moves is its declared type,
# which is the `AggregationType` enum on v41, v42 and most 2.43.1 boots, so the property takes
# its type from `dataElement.aggregationType` on the same server.
BOOT_DEPENDENT_PROPERTIES: tuple[BootDependentProperty, ...] = (
    BootDependentProperty(
        schema_name="categoryOption",
        property_name="aggregationType",
        reference_schema_name="dataElement",
        writable=True,
        bugs_ref="BUGS.md#95",
    ),
)


def apply_schema_patches(manifest: SchemasManifest) -> SchemasManifest:
    """Return a copy of `manifest` with every boot-dependent property pinned to its stable type."""
    patched = manifest.model_copy(deep=True)
    schemas_by_name = {schema.name: schema for schema in patched.schemas}
    for pin in BOOT_DEPENDENT_PROPERTIES:
        target = _property(schemas_by_name.get(pin.schema_name), pin.property_name)
        reference = _property(schemas_by_name.get(pin.reference_schema_name), pin.property_name)
        if target is None or reference is None or reference.propertyType != "CONSTANT":
            continue
        target.propertyType = reference.propertyType
        target.klass = reference.klass
        target.constants = list(reference.constants or [])
        target.writable = pin.writable
    return patched


def _property(schema: Schema | None, property_name: str) -> SchemaProperty | None:
    """Find a property by name on `schema`, or None when either is missing."""
    if schema is None:
        return None
    return next((prop for prop in schema.properties if prop.name == property_name), None)
