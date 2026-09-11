"""The plugin host of dhis2w: pluginkit extension points, the contribution model, and discovery.

A plugin is an object with one `@extension` method, `contribute(version_key)`, that returns a
`Contribution` naming the plugin and the modules that mount its CLI sub-app and register its MCP
tools. The built-in plugins are the `plugin` objects of the `dhis2w_core.v{41,42,43}.plugins.*`
packages; a plugin pack in its own distribution advertises its object under the
`dhis2w.plugins.v1` entry-point group. The CLI and the MCP server load one `PluginHost` at startup
and mount every contribution from it.

v43 is the canonical baseline and the default plugin tree. Every tree's client re-binds its
accessors to the server's major on connect, so the default tree does not constrain which server an
unpinned profile may talk to.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Mapping
from typing import Any

from pluginkit import Extension, ExtensionPoint, PluginManager
from pydantic import BaseModel, ConfigDict

PROJECT_NAME = "dhis2w"
#: The contract version is part of the group name, so an incompatible contract ships as a new group.
ENTRY_POINT_GROUP = "dhis2w.plugins.v1"
DEFAULT_VERSION_KEY = "v43"
SUPPORTED_VERSION_KEYS: frozenset[str] = frozenset({"v41", "v42", "v43"})

extension_point = ExtensionPoint(PROJECT_NAME)
extension = Extension(PROJECT_NAME)


class Contribution(BaseModel):
    """What one plugin adds to dhis2w: a name, a description, and the modules that mount its surfaces.

    `cli_module` names a module with a `register(app)` function that mounts the plugin's Typer
    sub-app on the root CLI; `mcp_module` names a module with a `register(server)` function that
    registers the plugin's tools on the FastMCP server. Either may be absent. The modules are
    imported only when a surface is mounted, so `d2w --help` never pays for the MCP dependencies.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    cli_module: str | None = None
    mcp_module: str | None = None

    def mount_cli(self, app: Any) -> None:
        """Mount the plugin's CLI sub-app on `app` when the plugin has one."""
        if self.cli_module is not None:
            importlib.import_module(self.cli_module).register(app)

    def register_mcp(self, server: Any) -> None:
        """Register the plugin's MCP tools on `server` when the plugin has any."""
        if self.mcp_module is not None:
            importlib.import_module(self.mcp_module).register(server)


@extension_point
def contribute(version_key: str) -> Contribution:
    """Collect what each plugin adds for the plugin tree `version_key` (`v41`, `v42` or `v43`)."""
    raise NotImplementedError("an extension point is a declaration; call it via PluginManager.caller(...)")


class PluginLoadFailure(BaseModel):
    """An entry point under `dhis2w.plugins.v1` that could not be loaded or registered."""

    model_config = ConfigDict(frozen=True)

    name: str
    error: str


class PluginHost(BaseModel):
    """Every contribution collected for one plugin tree, in mount order, plus what failed to load."""

    model_config = ConfigDict(frozen=True)

    version_key: str
    contributions: tuple[Contribution, ...]
    failures: tuple[PluginLoadFailure, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        """The contribution names in mount order."""
        return tuple(contribution.name for contribution in self.contributions)

    def get(self, name: str) -> Contribution | None:
        """The contribution called `name`, or None."""
        return next((contribution for contribution in self.contributions if contribution.name == name), None)

    def mount_cli(self, app: Any) -> None:
        """Mount every contribution's CLI sub-app on the root Typer app."""
        for contribution in self.contributions:
            contribution.mount_cli(app)

    def register_mcp(self, server: Any) -> None:
        """Register every contribution's MCP tools on the FastMCP server."""
        for contribution in self.contributions:
            contribution.register_mcp(server)


def resolve_startup_version() -> str:
    """Pick the plugin-tree version key from the active profile (best-effort).

    Resolution chain (first match wins):

    1. `profile.version` from the active profile (set via `d2w profile add NAME ... --version v43`
       or hand-edited in `profiles.toml`). A pin here wins over `DHIS2_VERSION`.
    2. `DHIS2_VERSION` env var (`v41` / `v42` / `v43`). Applies only when the active profile has no
       `version` pin, so `make verify-examples DHIS2_VERSION=v41` targets the v41 tree against an
       unpinned profile without hand-editing it. A bare digit (`41`) is not recognized.
    3. `DEFAULT_VERSION_KEY` (`"v43"`), the canonical baseline. Every tree's client re-binds its
       accessors to the server's major on connect, so the default tree constrains only which plugin
       tree loads, not which server an unpinned profile may reach.

    Falls back to `DEFAULT_VERSION_KEY` on any resolution failure (no profile configured, corrupt
    TOML, ...) so the CLI / MCP bootstrap never crashes; the wire client auto-detects regardless.
    """
    import os  # noqa: PLC0415 — scoped to startup discovery, avoids import-time cycles

    try:
        from dhis2w_core.profile import resolve

        resolved = resolve()
    except Exception:  # noqa: BLE001 — startup discovery must not raise
        resolved = None
    if resolved is not None and resolved.profile.version is not None:
        return resolved.profile.version.value
    env_version = os.environ.get("DHIS2_VERSION", "").strip()
    if env_version in SUPPORTED_VERSION_KEYS:
        return env_version
    return DEFAULT_VERSION_KEY


def load_plugin_host(
    version_key: str = DEFAULT_VERSION_KEY,
    *,
    group: str = ENTRY_POINT_GROUP,
    extra: Mapping[str, object] | None = None,
) -> PluginHost:
    """Discover the plugins for `version_key`, call `contribute()` once each, and return the host.

    Entry points under `group` load first and resiliently: a pack that fails to import is recorded
    in `PluginHost.failures` instead of blocking the CLI. The built-in plugins of
    `dhis2w_core.{version_key}.plugins.*` register next under their module path, and `extra`
    registers plugin objects that are not installed as distributions (tests, embedded hosts).
    Contributions come back sorted by name so the command tree and the tool list are stable.
    """
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(importlib.import_module(__name__))
    report = manager.load_entrypoints_report(group)
    for module_path, plugin in _builtin_plugins(version_key).items():
        manager.register(plugin, name=module_path)
    for name, plugin in (extra or {}).items():
        manager.register(plugin, name=name)
    # The extension point's return annotation is a declaration, not an enforcement: anything that
    # is not a Contribution is not mounted.
    collected = manager.caller(contribute).collect_with_plugins(version_key=version_key)
    contributions = sorted(
        (value for _, value in collected if isinstance(value, Contribution)),  # pyright: ignore[reportUnnecessaryIsInstance]
        key=lambda contribution: contribution.name,
    )
    failures = tuple(PluginLoadFailure(name=failure.name, error=str(failure.error)) for failure in report.failed)
    return PluginHost(version_key=version_key, contributions=tuple(contributions), failures=failures)


def _builtin_plugins(version_key: str) -> dict[str, object]:
    """The `plugin` objects of the tree's plugin packages, keyed by module path; empty for an unknown tree."""
    try:
        package = importlib.import_module(f"dhis2w_core.{version_key}.plugins")
    except ImportError:
        return {}
    found: dict[str, object] = {}
    for _, name, _is_package in pkgutil.iter_modules(package.__path__):
        module_path = f"dhis2w_core.{version_key}.plugins.{name}"
        plugin = getattr(importlib.import_module(module_path), "plugin", None)
        if plugin is not None:
            found[module_path] = plugin
    return found
