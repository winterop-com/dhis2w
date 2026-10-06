"""Unit tests for the local OpenAPI spec patches."""

from __future__ import annotations

import copy
from typing import Any

from dhis2w_codegen.spec_patches import apply_patches

_AGGREGATION_TYPE_REF = {"$ref": "#/components/schemas/AggregationType"}


def _components(aggregation_type: dict[str, Any], page_item_ref: str, instant_first: str) -> dict[str, dict[str, Any]]:
    """Build the boot-dependent components the way one DHIS2 boot might emit them."""
    instant_branches = [{"type": "integer", "format": "int64"}, {"type": "string", "format": "date-time"}]
    if instant_first == "string":
        instant_branches.reverse()
    return {
        "AggregationType": {"type": "string", "enum": ["SUM", "AVERAGE"]},
        "CategoryOption": {"type": "object", "properties": {"aggregationType": aggregation_type}},
        "CategoryOptionParams": {"type": "object", "properties": {"aggregationType": aggregation_type}},
        "EntityType": {"type": "any", "description": "The actual type is unknown."},
        "Instant": {"oneOf": instant_branches},
        "Page": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"$ref": f"#/components/schemas/{page_item_ref}"}}},
        },
        "SchemaObject": {"type": "object", "properties": {"$ref": {"type": "any"}}},
    }


def test_every_boot_variant_patches_to_one_shape() -> None:
    """Two boots that disagree on every flip-prone component patch to identical components (DHIS2_ISSUES.md #133)."""
    first = _components(_AGGREGATION_TYPE_REF, "TrackerRelationship", "integer")
    second = _components({"type": "boolean"}, "EntityType", "string")

    apply_patches(first)
    apply_patches(second)

    assert first == second
    assert first["CategoryOption"]["properties"]["aggregationType"] == _AGGREGATION_TYPE_REF
    assert first["Page"]["properties"]["items"] == {"type": "array", "items": {}}
    assert [branch["type"] for branch in first["Instant"]["oneOf"]] == ["integer", "string"]
    assert first["SchemaObject"]["properties"]["$ref"] == {"type": "string"}
    assert "EntityType" not in first


def test_referenced_placeholder_is_kept() -> None:
    """`EntityType` stays when something other than a pinned property still references it."""
    components = _components(_AGGREGATION_TYPE_REF, "TrackerRelationship", "integer")
    components["Holder"] = {"type": "object", "properties": {"entity": {"$ref": "#/components/schemas/EntityType"}}}

    apply_patches(components)

    assert "EntityType" in components


def test_patch_is_idempotent() -> None:
    """A second pass over patched components changes nothing."""
    components = _components({"type": "boolean"}, "EntityType", "string")
    apply_patches(components)
    patched = copy.deepcopy(components)

    apply_patches(components)

    assert components == patched


def test_reference_pin_skips_a_missing_component() -> None:
    """A tree without the `AggregationType` component keeps its inline enum instead of a dangling `$ref`."""
    inline_enum = {"type": "string", "enum": ["SUM", "AVERAGE"]}
    components = _components(inline_enum, "TrackerRelationship", "integer")
    del components["AggregationType"]

    apply_patches(components)

    assert components["CategoryOption"]["properties"]["aggregationType"] == inline_enum
