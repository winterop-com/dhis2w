"""Root pytest configuration: load the test environment core ships as a pytest plugin.

`dhis2w_core.testing` carries the respx mocker default, the colour-forcing environment
cleanup, the autouse profile-environment reset, the autouse browser-launch guard, and the
version-tree fixtures. The root conftest is the one file pytest allows `pytest_plugins` in,
and a plugin pack in another repository opts in the same way from its own root conftest.
"""

from __future__ import annotations

pytest_plugins = ["dhis2w_core.testing"]
