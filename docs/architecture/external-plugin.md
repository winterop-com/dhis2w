# Shipping an external plugin

`dhis2w-core`'s plugin host (`dhis2w_core.plugin`) is a
[pluginkit](https://pypi.org/project/pluginkit/) manager. It draws plugin
objects from two sources at CLI startup:

1. A package scan over the plugin tree `resolve_startup_version()` picks — v43
   unless the active profile or `DHIS2_VERSION` names another major (see
   [Version-aware clients](versioning.md)). On the default that is
   `dhis2w_core.v43.plugins.*`, which picks up every first-party plugin under
   `packages/dhis2w-core/src/dhis2w_core/v43/plugins/`.
2. The `dhis2w.plugins.v1` entry-point group — any separately-installed Python
   package can advertise a plugin object there.

`load_plugin_host(version_key)` registers everything it finds, calls each
plugin's `contribute(version_key)` extension once, and returns a `PluginHost`
holding the collected contributions sorted by name.

**External plugins are full first-class citizens.** They get the same
access to `Dhis2Client`, the same profile resolution, the same MCP
integration, and the same CLI mounting — no hooks, no registry file, no
core code changes.

## The contract

Three things make a package a valid plugin pack:

1. A plugin object with one `@extension` method, `contribute(self, version_key)`,
   returning a `Contribution`:

    ```python
    from dhis2w_core.plugin import Contribution, extension


    class _HelloPlugin:
        """Plugin object — the entry-point attribute dhis2w-core imports."""

        @extension
        def contribute(self, version_key: str) -> Contribution:
            """Contribute `d2w hello` and the `hello_say` MCP tool."""
            return Contribution(
                name="hello",
                description="Greets the authenticated user via /api/me.",
                cli_module="dhis2w_plugin_hello.cli",
                mcp_module="dhis2w_plugin_hello.mcp",
            )


    plugin = _HelloPlugin()
    ```

    The object is a **plain class**, not a pydantic model: pluginkit scans the
    object's attributes to find the extension, and a `BaseModel` subclass raises
    during that scan. `version_key` is the plugin tree the host is loading, so a
    pack that behaves differently per DHIS2 major branches on it; a
    version-neutral pack ignores it.

2. `cli_module` and `mcp_module` name modules, not objects. Each is imported
   lazily — only when that surface is mounted — and must expose a `register`
   function: `register(app)` adds the Typer sub-app to the root CLI,
   `register(server)` adds the tools to the FastMCP server. Either field may be
   left unset; the corresponding surface then stays empty.

3. An entry-point line in `pyproject.toml` pointing at the plugin object:

    ```toml
    [project.entry-points."dhis2w.plugins.v1"]
    <pack-name> = "your_package:plugin"
    ```

    The contract version lives in the group name: `dhis2w.plugins.v1` is what the
    host loads, and an incompatible contract would ship as a new group. The name
    on the left of `=` is what the host registers the object under; the name that
    reaches `d2w <name>` is the `Contribution.name`.

That's the entire contract. Everything else (the `service.py` / `cli.py` /
`mcp.py` file split) is convention.

## The reference implementation

`examples/plugin-external/` ships a minimal runnable pack
(`dhis2w-plugin-hello`) that greets the authenticated DHIS2 user:

```
examples/plugin-external/
├── pyproject.toml              [project.entry-points."dhis2w.plugins.v1"]
│                                  hello = "dhis2w_plugin_hello:plugin"
└── src/dhis2w_plugin_hello/
    ├── __init__.py             exports `plugin = _HelloPlugin()`
    ├── service.py              uses `open_client(profile)` like first-party plugins
    ├── cli.py                  `register(app)` mounts the Typer sub-app as `d2w hello`
    └── mcp.py                  `register(server)` adds the FastMCP tool `hello_say`
```

Install + verify:

```bash
uv add --editable examples/plugin-external/
d2w --help | grep hello
# hello        External plugin example.

d2w hello say
# Hello, admin admin!
```

## Why CLI + MCP parity is voluntary

Every first-party plugin ships both — same typed call from either surface
is a hard rule in this workspace. External plugins aren't obligated. A
plugin that only makes sense in a terminal can skip MCP registration; an
agent-only tool can skip the CLI side. Leave the field unset:

```python
return Contribution(
    name="hello",
    description="An agent-only pack.",
    mcp_module="dhis2w_plugin_hello.mcp",  # no cli_module — nothing mounts on `d2w`
)
```

## Error behaviour

A pack that does not import — not installed in the current environment, a typo
in the import path — is recorded in `PluginHost.failures` as a
`PluginLoadFailure` with the entry-point name and the error text, and the rest
of the host loads normally. A broken pack never takes down `d2w --help`;
inspect `load_plugin_host(...).failures` to see what dropped out.

Mounting is the loud half: if a plugin raises while its `cli_module` or
`mcp_module` registers, that propagates and the CLI aborts. Fail loudly when
the plugin itself is broken; stay quiet when the environment doesn't have it.

## Testing an external plugin

Same tooling as first-party: respx for HTTP mocking, Typer's `CliRunner`
for CLI verification, `fastmcp.Client` for MCP tools. Nothing plugin-
specific — test `service.py` directly, test `cli.py` via `CliRunner`
against a fake `Resources` or a mocked `open_client`.

Take the environment those tests run under from core rather than copying a
`conftest.py`: depend on `dhis2w-core[testing]` and put
`pytest_plugins = ["dhis2w_core.testing"]` in the root `conftest.py`, as
[Testing strategy](../testing.md#reusing-the-test-environment-from-a-pack) describes.

A pack that is not installed as a distribution — a test fixture, an embedded
host — reaches the host through `load_plugin_host(version_key, extra={"hello": plugin})`,
which registers the object under the given name without an entry point.

## Publishing

`uv build` → `uv publish` (or PyPI Trusted Publishing via your own GitHub
Actions workflow). Users install your plugin alongside their `dhis2w-cli`
install — `uv tool install --with your-plugin-name dhis2w-cli` for a
global tool, or `uv add your-plugin-name` inside a project that already
has `dhis2w-cli`. A pack the host knows gets an extra on `dhis2w-cli`
instead, the way `dhis2w-security` is `'dhis2w-cli[security]'`. Version-pin `dhis2w-client` / `dhis2w-core` in your
`dependencies` if your plugin uses generated models that might move.
