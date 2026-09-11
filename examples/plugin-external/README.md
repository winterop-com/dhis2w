# dhis2w-plugin-hello — external plugin example

Minimal standalone package showing how an external Python package adds a
`d2w <command>` + an MCP tool **without touching this repo**. Everything
works through the `dhis2w.plugins.v1` entry-point group — dhis2w-core's
pluginkit host loads that group at startup, registers every plugin object it
finds, and mounts the `Contribution` each one returns.

## Layout

```
examples/plugin-external/
├── pyproject.toml              # [project.entry-points."dhis2w.plugins.v1"]
│                                  hello = "dhis2w_plugin_hello:plugin"
├── README.md
└── src/
    └── dhis2w_plugin_hello/
        ├── __init__.py         # exports `plugin = _HelloPlugin()`
        ├── service.py          # pure library code (uses open_client / profiles)
        ├── cli.py              # `register(app)` mounts the Typer sub-app as `d2w hello`
        └── mcp.py              # `register(server)` adds the FastMCP tool `hello_say`
```

Same layout every first-party plugin uses
(`packages/dhis2w-core/src/dhis2w_core/v43/plugins/*/`). The only extra step
external plugins need is the entry-point line in `pyproject.toml` —
first-party plugins get registered from a built-in package scan instead.

The plugin object is a plain class with one `@extension` method:

```python
from dhis2w_core.plugin import Contribution, extension


class _HelloPlugin:
    """Plugin object — the entry-point attribute dhis2w-core imports."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w hello` and the `hello_say` MCP tool."""
        return Contribution(
            name="hello",
            description="External plugin example — greets the authenticated user via /api/me.",
            cli_module="dhis2w_plugin_hello.cli",
            mcp_module="dhis2w_plugin_hello.mcp",
        )


plugin = _HelloPlugin()
```

Not a pydantic model: pluginkit scans the object's attributes to find the
extension, and a `BaseModel` subclass raises during that scan.

## Install + use

```bash
# From the repo root:
uv add --editable examples/plugin-external/

# Verify it registered:
d2w --help | grep hello
#   hello        External plugin example.

d2w hello say
#   Hello, admin admin!

d2w hello say --greeting "Hei"
#   Hei, admin admin!

# Uninstall when done:
uv remove dhis2w-plugin-hello
```

MCP equivalent:

```python
from fastmcp import Client
from dhis2w_mcp.server import build_server

async with Client(build_server()) as client:
    result = await client.call_tool("hello_say", {"greeting": "Hei"})
    print(result.structured_content)  # {"data": "Hei, admin admin!"}
```

## What to copy for your own plugin

1. Replace `dhis2w_plugin_hello` with your package name everywhere (dir +
   entry-point + `cli_module` / `mcp_module` paths).
2. Change the entry-point key (`hello = "..."`) to your plugin's name —
   the host registers the object under it, and the `Contribution.name` is
   what appears in `d2w --help`.
3. Add whatever DHIS2 calls your plugin needs in `service.py`, expose
   them via `cli.py` + `mcp.py`, keep the plugin object in `__init__.py`.

That's it. The CLI-vs-MCP parity is voluntary: leave `cli_module` or
`mcp_module` unset and that surface stays empty. A pack that fails to
import is reported in `PluginHost.failures` rather than taking the CLI
down with it.
