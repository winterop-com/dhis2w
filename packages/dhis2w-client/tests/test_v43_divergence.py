"""Pinned tests for every v43-specific divergence from the v42 baseline.

Mirror of `test_v41_divergence.py` for the v43 hand-written tree. Each
asserts the static shape of a known v43 divergence so future refactors
or codegen regens that accidentally realign with v42 surface here.

Categories covered:

- v43 CategoryCombo: `categorys` legacy alias dropped from the
  write-payload path (`categories` is the sole field name).

Mocked-then-live coverage for these lives in the BUGS regression suite
(paired `test_bug_34_*` in `test_upstream_bugs.py`); this
file's tests stay structural — they don't hit the wire, they just
assert the v43 source code shape stayed divergent.

When a new v43 divergence lands, add a test below + a one-line entry
to "Categories covered".
"""

from __future__ import annotations

import inspect

# ----- v43 CategoryCombo ----------------------------------------------------


def test_v43_category_combo_create_payload_uses_categories_key() -> None:
    """v43 `CategoryCombosAccessor.create` POSTs `categories` (wire spelling), not the v42 `categorys` alias.

    v43 dropped the historical `categorys` alias. Inspects the
    `create` method's source body to confirm the payload key is the
    wire-correct `categories`. (The module-level docstring still
    mentions `categorys` to explain the historical alias — that's fine,
    we only care about the actual POST payload.)
    """
    from dhis2w_client.v43.category_combos import CategoryCombosAccessor

    create_source = inspect.getsource(CategoryCombosAccessor.create)
    # The payload dict literal must include the `categories` key and must NOT
    # include the misspelled `categorys` alias.
    assert '"categories":' in create_source, (
        f'v43 CategoryCombosAccessor.create must build a `"categories":` payload key. Source body:\n{create_source}'
    )
    assert '"categorys":' not in create_source, (
        f'v43 CategoryCombosAccessor.create must not use the v42 `"categorys":` alias — '
        f"v43 silently no-ops on it (BUGS.md #34). Source body:\n{create_source}"
    )
