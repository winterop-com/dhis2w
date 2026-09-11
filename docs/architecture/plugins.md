# Plugin runtime

`dhis2w-core` is the shared runtime that both `dhis2w-cli` and `dhis2w-mcp` build on. Its central contract is the **plugin** — a small object that every capability (system info, metadata CRUD, tracker, analytics, codegen, …) implements so the CLI and MCP surfaces never drift out of parity.

## The contract

```python
# packages/dhis2w-core/src/dhis2w_core/plugin.py
class Contribution(BaseModel):
    """What one plugin adds to dhis2w: a name, a description, and the modules that mount its surfaces."""

    name: str  # stable id, e.g. "system"
    description: str  # one-line human-readable summary
    cli_module: str | None = None  # module with `register(app)`
    mcp_module: str | None = None  # module with `register(server)`


@extension_point
def contribute(version_key: str) -> Contribution:
    """Collect what each plugin adds for the plugin tree `version_key` (`v41`, `v42` or `v43`)."""
```

A plugin is a plain Python object with one `@extension` method that answers the
`contribute` extension point:

```python
class _SystemPlugin:
    """Plugin descriptor for the system capability."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w system` and the `whoami` / `system_info` MCP tools."""
        return Contribution(
            name="system",
            description="DHIS2 system info and current-user access.",
            cli_module="dhis2w_core.v43.plugins.system.cli",
            mcp_module="dhis2w_core.v43.plugins.system.mcp",
        )


plugin = _SystemPlugin()
```

The object is a plain class, never a pydantic model: pluginkit scans the object's
attributes to find the extension, and a `BaseModel` subclass raises during that
scan. A plugin with one surface leaves the other module unset — `schema` and `dev`
have no `mcp_module`, `user-group` and `user-role` no `cli_module` (the `user`
plugin mounts their commands as sub-groups).

Naming a module rather than passing a callable keeps the import lazy: nothing under
`mcp_module` is imported until the MCP server registers, so `d2w --help` never pays
for the FastMCP dependencies.

## Discovery

The host machinery is [pluginkit](https://pypi.org/project/pluginkit/).
`load_plugin_host(version_key)` builds a `PluginManager`, registers every plugin
object it can find, calls `contribute(version_key)` once per plugin, and returns a
`PluginHost` whose `contributions` are sorted by name. Two sources feed it:

1. **Built-ins** — `pkgutil.iter_modules()` walks the first-party plugin folder of the tree `resolve_startup_version()` picks (`dhis2w_core.v43.plugins` on the default). Each sub-module exposes a module-level `plugin = _MyPlugin()`, registered under its module path. No registry list to maintain; adding a folder is enough.
2. **External** — the `dhis2w.plugins.v1` entry-point group, registered under the entry-point name. A separately-installed package ships its own plugin by declaring:

    ```toml
    [project.entry-points."dhis2w.plugins.v1"]
    my-capability = "my_package.plugin:plugin"
    ```

    `dhis2w-fhir` already does this — `d2w fhir` mounts without any code living under `dhis2w-core`. See [Shipping an external plugin](external-plugin.md).

The contract version is part of the group name, so an incompatible contract would
ship as `dhis2w.plugins.v2` rather than breaking installed packs. A pack that fails
to import is reported in `PluginHost.failures` instead of taking the CLI down.

Tests and embedded hosts pass plugin objects that are not installed as
distributions through `load_plugin_host(version_key, extra={"name": plugin})`.

## Standard layout per plugin

Every first-party plugin lives in `packages/dhis2w-core/src/dhis2w_core/v43/plugins/<name>/`:

```
<name>/
├── __init__.py        # exports `plugin = _MyPlugin()`
├── service.py         # async pure functions — single source of truth
├── cli.py             # Typer sub-app + register(app) helper
├── mcp.py             # FastMCP tool registrations + register(server) helper
└── models.py          # (optional) plugin-internal pydantic view-models
```

- `service.py` holds the **real work** — async functions that take a `Profile` and return typed results.
- `cli.py` wraps `service.py` with Typer decorators + rich printing.
- `mcp.py` wraps `service.py` with `@server.tool()` decorators.

Both `cli.py` and `mcp.py` are thin — they format I/O and nothing else. The CLI and MCP surfaces cannot drift because they share the same underlying function.

## The `system` plugin as a reference

The smallest complete plugin lives at `dhis2w_core/v43/plugins/system/` — its
`__init__.py` is the descriptor above, and the three modules beside it are:

```python
# service.py
async def whoami(profile: Profile) -> Me:
    async with open_client(profile) as client:
        return await client.system.me()


async def system_info(profile: Profile) -> SystemInfo:
    async with open_client(profile) as client:
        return await client.system.info()
```

```python
# cli.py
@app.command("whoami")
def whoami_command() -> None:
    me = asyncio.run(service.whoami(profile_from_env()))
    typer.echo(f"{me.username} ({me.displayName or '-'})")
```

```python
# mcp.py
def register(server: Any) -> None:
    @server.tool()
    async def whoami() -> Me:
        return await service.whoami(profile_from_env())
```

That's a full capability in ~30 lines. Both `d2w system whoami` and an MCP agent's `whoami` tool call go through `service.whoami` end-to-end.

## Profile resolution

Plugins don't resolve profiles themselves. They call `profile_from_env()` at tool-call time, which walks the standard resolution chain (first match wins): an explicit `--profile <name>` arg → `DHIS2_PROFILE` env var → raw `DHIS2_URL` + (`DHIS2_PAT` | `DHIS2_USERNAME`+`DHIS2_PASSWORD`) env (PAT or Basic only — OAuth2 needs a saved profile) → project-local `.dhis2/profiles.toml` default → user-global `~/.config/dhis2/profiles.toml` default. This keeps the CLI and MCP surfaces completely symmetric — neither needs to thread "what DHIS2 should I talk to?" through arguments. See [Profiles](profiles.md) for the full chain.

## Why not inheritance?

There is no plugin base class. A plugin object is whatever carries a `contribute`
method marked with `@extension` — pluginkit finds it by scanning attributes, not by
walking a class hierarchy. External packages import two names from `dhis2w-core`
(`Contribution` and `extension`) and nothing else. Loose coupling and zero
inheritance overhead.

A new capability of the host is a new extension point declared in
`dhis2w_core.plugin`, never a hand-rolled registry or entry-point scan beside it.
