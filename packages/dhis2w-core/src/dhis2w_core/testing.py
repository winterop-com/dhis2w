"""Pytest plugin carrying the test environment every dhis2w suite runs under.

A suite opts in from its root `conftest.py` with `pytest_plugins = ["dhis2w_core.testing"]`,
which is the one file pytest allows that name in. There is deliberately no `pytest11` entry
point: the autouse fixtures here reshape the process environment and stub `webbrowser`, which
belongs to a dhis2w suite and to nothing else installed alongside it.

Importing this module sets the respx mocker default and clears the colour-forcing variables;
collecting it as a plugin adds the two autouse fixtures and the four version-tree fixtures.

The colour-forcing variables are cleared at import rather than from a fixture. `cli_output`
builds its `Console` at module scope, so the setting is captured the moment a test module
imports the CLI - earlier than any fixture runs. pytest imports the root conftest, and through
it this plugin, before it imports test modules, which is the only point early enough to matter.

The profile-resolution variables are cleared from a fixture rather than at import, because
they are set *after* this module is imported: pytest imports the root conftest first and the
per-package ones second, and a developer's own shell can export them too. Only a per-test
reset catches both.
"""

from __future__ import annotations

import os
import webbrowser
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from types import ModuleType

import httpx
import pytest

# Imported for its import side effect: it registers the "httpcore2" respx mocker.
import pytest_httpx2  # noqa: F401  # pyright: ignore[reportUnusedImport]
import respx
import respx.mocks

#: Every `respx.mock` / `respx.MockRouter` in the suite intercepts httpx2 traffic. respx reads
#: this name lazily when a router starts, so one assignment here covers routers created at
#: module import time as well as inside tests. The `httpcore2` mocker is the one pytest-httpx2
#: registers; respx's own default patches the old `httpcore`, which nothing shipped uses.
respx.mocks.DEFAULT_MOCKER = "httpcore2"

#: Variables that make Rich render as if stdout were a terminal - ANSI colour, 80-column
#: panels, wrapped lines - even under a captured stream. `FORCE_COLOR` / `CLICOLOR_FORCE` are
#: developer-shell settings; `GITHUB_ACTIONS` and `TF_BUILD` are set by the CI runners
#: themselves, and Rich treats either as a colour terminal so its output looks good in CI
#: logs. Under `CliRunner` that means assertions like `assert "--code-source" in result.output`
#: fail on escape codes and panel wrapping. Tests assert on what the CLI says, not on how a
#: terminal paints it.
_COLOUR_FORCING_VARIABLES = ("FORCE_COLOR", "CLICOLOR_FORCE", "GITHUB_ACTIONS", "TF_BUILD")

for _variable in _COLOUR_FORCING_VARIABLES:
    os.environ.pop(_variable, None)


#: Variables `dhis2w_core.profile.resolve()` consults before it ever reads a `profiles.toml`:
#: `DHIS2_PROFILE` names a profile outright, and `DHIS2_URL` plus one credential pair
#: (`DHIS2_PAT`, or `DHIS2_USERNAME` + `DHIS2_PASSWORD`, with `DHIS2_VERSION` pinning the major)
#: synthesises the `env-raw` profile. Both layers outrank the project and global TOML files.
#:
#: That precedence makes them process-wide state a test cannot isolate by pointing `HOME` and
#: `XDG_CONFIG_HOME` at a `tmp_path`: a fixture can own every TOML file the resolver will read
#: and still lose to an ambient `DHIS2_URL`. A developer who has run `make -C infra up-seeded`
#: has exactly that - the local stack's URL and credentials, exported by their shell or read out
#: of `infra/home/credentials/.env.auth` - so a profile-resolving test would silently resolve
#: against localhost instead of the profile the fixture wrote.
#:
#: Tests that want the seeded stack ask for it explicitly (`local_url` / `local_pat` fixtures,
#: then `monkeypatch.setenv` inside the test), which lands after this fixture and therefore wins.
_PROFILE_RESOLUTION_VARIABLES = (
    "DHIS2_PROFILE",
    "DHIS2_URL",
    "DHIS2_PAT",
    "DHIS2_USERNAME",
    "DHIS2_PASSWORD",
    "DHIS2_VERSION",
)

#: Every entry point `webbrowser` offers for handing a URL to the desktop. `capture_code`
#: calls `webbrowser.open`, and the module's other two names reach the same browsers, so all
#: three are stubbed together: leaving one live would let a future call site slip through.
_BROWSER_LAUNCHERS = ("open", "open_new", "open_new_tab")

#: The wire version each core version tree claims from `/api/system/info`, so a client opened
#: inside a parametrized test dispatches its accessors to the tree under test.
_CORE_WIRE_VERSIONS = {"v41": "2.41.8.1", "v42": "2.42.0", "v43": "2.43.0"}


@pytest.fixture(autouse=True)
def _neutral_profile_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the env layers of profile resolution so no test inherits an ambient DHIS2 instance."""
    for variable in _PROFILE_RESOLUTION_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture(autouse=True)
def _no_browser_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that reaches the interactive OAuth2 login instead of opening a browser.

    The OAuth2 authorization-code flow runs when no usable cached token is found, and its
    first act is to open the developer's own browser at the instance's `/oauth2/authorize`
    and then wait five minutes for a redirect that will never arrive. A test that means to
    exercise a cached token but stores one the provider rejects hits exactly that path, so
    the failure surfaces as the developer's browser opening on a fabricated URL and the
    suite hanging - neither of which names the test that caused it.

    Raising here turns that into an immediate failure naming the URL and, through the
    traceback, the test. A test that legitimately drives a browser launch overrides the stub
    with its own `monkeypatch.setattr(webbrowser, "open", ...)`, which lands after this
    fixture and therefore wins.
    """

    def _refuse(url: str, *args: object, **kwargs: object) -> bool:
        raise AssertionError(
            f"a test reached the interactive OAuth2 login and tried to open a browser at {url!r}. "
            "Pass `open_browser=False`, inject a `redirect_capturer`, or store a token carrying "
            "this provider's `base_url` and `client_id` so the cached-token path is taken."
        )

    for launcher in _BROWSER_LAUNCHERS:
        monkeypatch.setattr(webbrowser, launcher, _refuse)


@pytest.fixture(params=list(_CORE_WIRE_VERSIONS))
def core_version(request: pytest.FixtureRequest) -> str:
    """Parametrize a core plugin test across all three version trees (v41/v42/v43)."""
    return str(request.param)


@pytest.fixture
def plugin_service(core_version: str) -> Callable[[str], ModuleType]:
    """Return a helper that imports a plugin's service module for the parametrized version tree."""

    def _service(plugin_name: str) -> ModuleType:
        return import_module(f"dhis2w_core.{core_version}.plugins.{plugin_name}.service")

    return _service


@pytest.fixture
def mock_system_info() -> Callable[..., None]:
    """Return a helper that mocks `/api/system/info` to a version key's wire version (respx-active)."""

    def _mock(version_key: str, base_url: str = "https://dhis2.example") -> None:
        respx.get(f"{base_url}/api/system/info").mock(
            return_value=httpx.Response(200, json={"version": _CORE_WIRE_VERSIONS[version_key]}),
        )

    return _mock


@pytest.fixture
def core_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write a profiles.toml with a Basic `probe` profile the services can open_client on."""
    config_dir = tmp_path / ".config" / "dhis2"
    config_dir.mkdir(parents=True)
    (config_dir / "profiles.toml").write_text(
        """
default = "probe"

[profiles.probe]
base_url = "https://dhis2.example"
auth = "basic"
username = "admin"
password = "district"
"""
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir.parent))
    monkeypatch.delenv("DHIS2_PROFILE", raising=False)
    monkeypatch.chdir(tmp_path)
