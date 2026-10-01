"""Unit tests for `infra/scripts/clone_version_tree.py`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "infra" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from clone_version_tree import _leftovers, _rewrite  # noqa: E402 — path-prepend intentional


@pytest.mark.parametrize(
    ("original", "rewritten"),
    [
        ("from dhis2w_client.v43.client import Dhis2Client", "from dhis2w_client.v44.client import Dhis2Client"),
        ('rebind_accessors_for_version(self, key, home="v43")', 'rebind_accessors_for_version(self, key, home="v44")'),
        ("version=Dhis2.V43", "version=Dhis2.V44"),
        ("set_labels is v43-only", "set_labels is v43+"),
        ("2.43.1 refuses orgUnits", "2.43.1 refuses orgUnits"),
    ],
)
def test_rewrite(original: str, rewritten: str) -> None:
    """Module paths, keys and enum members move; `v43-only` becomes `v43+`; release strings stay."""
    assert _rewrite(original, "43", "44") == rewritten


def test_leftovers_flag_rewritten_enumerations(tmp_path: Path) -> None:
    """An enumeration the rewrite turned into `v41 / v42 / v44` is listed for review."""
    (tmp_path / "service.py").write_text(
        '"""Plugin tree: `v41` / `v42` / `v44`."""\nfrom dhis2w_core.v44 import plugins\n', encoding="utf-8"
    )

    flagged = [leftover.line_number for leftover in _leftovers(tmp_path, "43", "44")]

    assert flagged == [1]
