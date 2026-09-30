# dhis2w

[![CI](https://github.com/winterop-com/dhis2w/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/winterop-com/dhis2w/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/dhis2w-cli?color=2C6693&label=PyPI)](https://pypi.org/project/dhis2w-cli/)
[![Python](https://img.shields.io/pypi/pyversions/dhis2w-client?color=3776AB)](https://pypi.org/project/dhis2w-client/)
[![DHIS2](https://img.shields.io/badge/DHIS2-41%20%7C%2042%20%7C%2043-2C6693)](https://winterop-com.github.io/dhis2w/architecture/versioning/)
[![License](https://img.shields.io/badge/license-Proprietary-lightgrey)](LICENSE)

A Python toolkit for DHIS2 — pure client library, CLI, and a shared plugin runtime, in one `uv` workspace, with the MCP server, the FHIR Implementation Guide tooling, and Playwright browser automation as plugin packs in their own repositories. Targets DHIS2 v41, v42, and v43, with v44 as a preview against a pinned 2.44 development build.

The repo lives at `winterop-com/dhis2w`; PyPI ships the three publishable members, and the plugin packs, under the `dhis2w-*` prefix. Not affiliated with DHIS2.

> **Learning path · step 1 of 8** — You are here. Quick install + profile + first CLI / Python call below. Next: the [contributor walkthrough](docs/walkthrough.md) for the local docker stack, or jump to a surface-specific tutorial — [CLI](docs/cli/tutorial.md), [Python](docs/client/tutorial.md), [MCP](https://winterop-com.github.io/dhis2w-mcp/tutorial/).

## Why this toolkit?

DHIS2 already has a lightweight, official Python client that returns plain JSON dictionaries — ideal when you want a thin wrapper and a few lines in a notebook. `dhis2w` is built for a different need: a typed, multi-surface toolkit you can depend on across instances and versions.

- **Typed, not stringly-typed.** Every response is a Pydantic model generated from DHIS2's own OpenAPI spec, so your editor autocompletes fields and the type checker catches a misspelled key before you run. No guessing dictionary keys against the docs.
- **One core, four surfaces.** The same typed client powers a Python library, a `d2w` CLI, an MCP server (the [`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) pack), and Playwright browser automation (the [`dhis2w-browser`](https://github.com/winterop-com/dhis2w-browser) pack) — all sharing one `service.py` per domain, so behaviour never drifts between them.
- **Built for AI agents.** The [`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) server exposes ~304 typed tools, one per CLI command, so any MCP host (Claude, Cursor) can drive a DHIS2 instance directly.
- **Version-aware by design.** Detects v41 / v42 / v43 / v44 on connect and binds the matching hand-written tree, so one codebase works across instances instead of branching on the wire shape yourself.
- **Real auth.** Basic, PAT, and OAuth2/OIDC with PKCE, behind a pluggable `AuthProvider` protocol, with a profile system for juggling multiple instances.
- **Production posture.** Strict ruff + mypy + pyright, ~1,150 tests, an mkdocs-material site, and runnable examples for every supported version.

Reach for the official client when you want the smallest possible dependency and raw JSON. Reach for `dhis2w` when you want types, a CLI, agent tooling, and version coverage in one place. Note that `dhis2w` is third-party.

## Workspace members

| Package | PyPI | Purpose |
| --- | --- | --- |
| [`dhis2w-client`](https://pypi.org/project/dhis2w-client/) | `uv add dhis2w-client` | Pure async httpx2 + pydantic DHIS2 client with pluggable auth (Basic, PAT, OAuth2/OIDC). Typed models from both `/api/schemas` and `/api/openapi.json` codegen. |
| [`dhis2w-core`](https://pypi.org/project/dhis2w-core/) | `uv add dhis2w-core` | Shared runtime: profile discovery, plugin registry, auth factory, token store, first-party plugins. |
| [`dhis2w-cli`](https://pypi.org/project/dhis2w-cli/) | `uv tool install dhis2w-cli` | Typer console script `d2w`. |
| `dhis2w-codegen` | _workspace-only_ | Generator that emits pydantic models + `StrEnum`s + CRUD accessors into `dhis2w_client.generated.v{N}/`. Two source-of-truth paths: `/api/schemas` for metadata resources, `/api/openapi.json` for instance-side shapes (tracker writes, envelopes, auth schemes). |

All three publishable packages release together (lockstep versioning); see [`docs/releasing.md`](docs/releasing.md).

## Plugin packs

These live in repositories of their own, publish to PyPI at the same version as this workspace, and build on `dhis2w-core`.

| Package | Repository | Purpose |
| --- | --- | --- |
| [`dhis2w-mcp`](https://pypi.org/project/dhis2w-mcp/) | [`winterop-com/dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) | FastMCP server `dhis2w-mcp` carrying the MCP tools of every built-in plugin. Install with `uv tool install dhis2w-mcp`. |
| [`dhis2w-mcp-bridge`](https://pypi.org/project/dhis2w-mcp-bridge/) | [`winterop-com/dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) | FastMCP server `dhis2w-mcp-bridge` — exposes the whole `d2w` CLI as a single `dhis2_cli` tool for small local models. |
| [`dhis2w-mcp-router`](https://pypi.org/project/dhis2w-mcp-router/) | [`winterop-com/dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) | Domain-neutral MCP router — fronts many upstream MCP servers behind two meta-tools (search + dispatch) so an agent gets lazy, searchable tool discovery instead of a huge up-front tool payload. |
| [`dhis2w-browser`](https://pypi.org/project/dhis2w-browser/) | [`winterop-com/dhis2w-browser`](https://github.com/winterop-com/dhis2w-browser) | Playwright helpers for DHIS2 UI automation — PAT minting, Playwright-driven OIDC login + consent, dashboard / viz / map screenshot capture. Mounted under `d2w browser` when the `[browser]` extra is installed on `dhis2w-cli`. |
| [`dhis2w-fhir`](https://pypi.org/project/dhis2w-fhir/) | [`winterop-com/dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) | FHIR Implementation Guide tooling mounted as `d2w fhir` through the `[fhir]` extra on `dhis2w-cli`: `init`, `generate`, `validate`, `forward`, `doctor`. Documented at <https://winterop-com.github.io/dhis2w-fhir/>. |
| [`dhis2w-fhir-serve`](https://pypi.org/project/dhis2w-fhir-serve/) | [`winterop-com/dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) | The FastAPI facade behind `d2w fhir serve`, with the browser capture UI. Installed with the `[serve]` extra on `dhis2w-cli`. |
| [`dhis2w-fhir-engine`](https://pypi.org/project/dhis2w-fhir-engine/) | [`winterop-com/dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) | FHIRPath, CQL, and quality-measure evaluation over FHIR data, with the R4 resource models; no DHIS2 dependency. |
| [`dhis2w-security`](https://github.com/winterop-com/dhis2w-security) | [`winterop-com/dhis2w-security`](https://github.com/winterop-com/dhis2w-security) | Security posture scanner mounted as `d2w security` through the `[security]` extra on `dhis2w-cli`. |

The LLM benchmark harness lives in [`dhis2w-integration`](https://github.com/winterop-com/dhis2w-integration), the control center that assembles this workspace and every plugin pack into one environment.

## Install

### Use the CLI

The CLI command is named **`d2w`** but the PyPI distribution is **`dhis2w-cli`** — that's why every install command spells out the package name explicitly.

```bash
# Install once, run forever — drops `d2w` on $PATH
uv tool install dhis2w-cli

# With the security posture scanner (the dhis2w-security pack mounts `d2w security`)
uv tool install 'dhis2w-cli[security]'

# With Playwright UI automation (browser screenshots, OIDC login, PAT minting)
uv tool install 'dhis2w-cli[browser]'
playwright install chromium    # one-time, after the install above

# With FHIR Implementation Guide tooling (the dhis2w-fhir pack mounts `d2w fhir`);
# add `serve` for the capture facade behind `d2w fhir serve`
uv tool install 'dhis2w-cli[fhir]'
uv tool install 'dhis2w-cli[fhir,serve]'

# Update to the latest release
uv tool upgrade dhis2w-cli

# Force a re-install (handy after PyPI publish issues / cache problems)
uv tool install --reinstall dhis2w-cli

# Check what's installed
uv tool list

# Remove
uv tool uninstall dhis2w-cli
```

**FHIR support** is the [`dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) plugin pack, documented at
<https://winterop-com.github.io/dhis2w-fhir/>: install `'dhis2w-cli[fhir]'` for `d2w fhir`, and `'dhis2w-cli[fhir,serve]'`
for the serving facade. Without the pack, `d2w fhir` prints that install command rather than failing as an unknown
command; `d2w browser` and `d2w security` do the same for their packs.

After `uv tool install dhis2w-cli`, run the CLI directly:

```bash
d2w --help
d2w --version  # also: -V — shows package version + active plugin tree
d2w system info --url https://play.im.dhis2.org/dev-2-43 --username admin --password district
```

`d2w --version` surfaces which plugin tree (`v41` / `v42` / `v43` / `v44`) the CLI booted with and where that came from in the resolution chain (`profile.version` → `DHIS2_VERSION` env → default `v43`). Helps debug "which DHIS2 major is this CLI talking to" without reading the profile by hand.

#### One-shot runs without installing — `uvx`

`uvx` is uv's "run-and-forget" runner — it fetches the package into a cache and runs the binary, with no permanent install:

```bash
# uvx <command>           # works when the binary name == the package name
# uvx --from <pkg> <cmd>  # required when they differ — that's our case

uvx --from dhis2w-cli d2w --help
uvx --from dhis2w-cli d2w system info --url https://play.im.dhis2.org/dev-2-43 --username admin --password district

# With the browser extra
uvx --from 'dhis2w-cli[browser]' d2w browser pat --url ...

# Force a cache refresh — pulls the latest published version
uvx --refresh --from dhis2w-cli d2w --help
```

`uv tool install` keeps the install in its own dedicated venv (separate from any project venv), so the `d2w` binary on your `$PATH` can't be perturbed by a `uv sync` somewhere else.

### Use the client library in your own project

```bash
# Inside a uv-managed project
uv add dhis2w-client
```

```python
from dhis2w_client import BasicAuth, Dhis2Client

async with Dhis2Client(
    base_url="https://play.im.dhis2.org/dev-2-43",
    auth=BasicAuth(username="admin", password="district"),
) as client:
    me = await client.system.me()
    print(me.username)
```

`dhis2w-client` is standalone — no dependency on `dhis2w-core` or the profile system. PyPI users who want the typed async client + generated metadata models stop here.

### Use the MCP server

[`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp), the MCP plugin pack, exposes ~304 typed tools (one per CLI command) over the MCP stdio transport when connected to a DHIS2 v42 instance; v43 adds a handful more for the v43-only schema fields. Connect any MCP host — Claude Desktop, Claude Code, Cursor, or anything that speaks stdio MCP.

The PyPI distribution name **is** the binary name here (`dhis2w-mcp`), so the `--from` dance isn't needed:

```bash
# Install once — drops `dhis2w-mcp` on $PATH
uv tool install dhis2w-mcp

# Update later
uv tool upgrade dhis2w-mcp

# Or run on demand without installing
uvx dhis2w-mcp

# Force a fresh fetch (after a new PyPI release)
uvx --refresh dhis2w-mcp
```

**Claude Desktop** — edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "dhis2": {
      "command": "uvx",
      "args": ["dhis2w-mcp"],
      "env": {
        "DHIS2_URL": "https://play.im.dhis2.org/dev-2-43",
        "DHIS2_USERNAME": "admin",
        "DHIS2_PASSWORD": "district"
      }
    }
  }
}
```

Restart Claude Desktop. PAT auth works the same way — replace the username/password pair with `"DHIS2_PAT": "d2p_..."`.

**Claude Code** — register from any shell:

```bash
claude mcp add d2w -s user \
  -e DHIS2_URL=https://play.im.dhis2.org/dev-2-43 \
  -e DHIS2_PAT=d2p_... \
  -- uvx dhis2w-mcp
```

`-s user` makes the server available across every project. Tools land in-session as `mcp__dhis2__system_whoami`, `mcp__dhis2__metadata_data_element_list`, etc.

**Cursor** — edit `~/.cursor/mcp.json` with the same JSON shape as Claude Desktop and reload.

The full per-client setup, profile-based auth (`.dhis2/profiles.toml` for OAuth2 / OIDC), tool-naming convention, and troubleshooting are in the [dhis2w-mcp documentation](https://winterop-com.github.io/dhis2w-mcp/).

### Use the MCP bridge (small local models)

For a **small model running on-box** (LM Studio / Ollama / llama.cpp) against data that can't leave the machine, `dhis2w-mcp-bridge` (from the same [`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) pack) exposes the whole CLI as a **single** tool, `dhis2_cli`, that the model drives by progressive discovery — ~one tool schema instead of ~304. (Why one tool, not many: [Bridge design](https://winterop-com.github.io/dhis2w-mcp/architecture/mcp-bridge/). Use the full `dhis2w-mcp` server above for capable cloud models.)

```bash
uv tool install dhis2w-mcp-bridge          # or run on demand: uvx dhis2w-mcp-bridge
```

**LM Studio** (native MCP client) — `~/.lmstudio/mcp.json`:

```json
{
  "mcpServers": {
    "dhis2": {
      "command": "dhis2w-mcp-bridge",
      "env": { "DHIS2_PROFILE": "local_basic", "DHIS2_MCP_READONLY": "1" }
    }
  }
}
```

The model then drives the CLI like a terminal, pulling help on demand:

```
dhis2_cli(["--help"])                                        # discover command groups
dhis2_cli(["metadata", "list", "dataElements", "--count"])   # {"resource":"dataElements","total":1037}
dhis2_cli(["schema", "dataElement"])                         # the type's fields (+ enum values)
```

`--json` is injected automatically; `DHIS2_MCP_READONLY=1` refuses writes (fail-closed). Full usage + read-only details: [the bridge guide](https://winterop-com.github.io/dhis2w-mcp/bridge/).

### Use the profile layer (env / TOML config)

The `dhis2w-cli` package and the `dhis2w-mcp` pack share the profile system of `dhis2w-core`, which walks `DHIS2_PROFILE` env → `./.dhis2/profiles.toml` → `~/.config/dhis2/profiles.toml`:

```bash
# One-shot bootstrap: prompts for URL + auth, saves a profile
d2w profile bootstrap mywork

# List what's known
d2w profile list

# Switch the default
d2w profile default mywork
```

```python
from dhis2w_core.client_context import open_client
from dhis2w_core.profile import profile_from_env

async with open_client(profile_from_env()) as client:
    me = await client.system.me()
    print(me.username)
```

PyPI consumers who want the library without the profile layer can construct `Dhis2Client(url, auth=BasicAuth(...))` directly — see `examples/client/library_only_auth.py`.

## CLI surface

Nineteen top-level domains; every plugin shares a `service.py` between the CLI and the MCP tools of the [`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) pack, so one typed call answers both surfaces.

| Command | What it covers |
| --- | --- |
| `d2w profile` | Manage DHIS2 profiles (Basic / PAT / OAuth2) + the default precedence chain |
| `d2w system` | `/api/system/info`, `/api/me`, minted UIDs |
| `d2w metadata` | List / get / export / import any metadata resource, with DHIS2's full filter + fields selector |
| `d2w data` | Aggregate data values + tracker reads + pushes |
| `d2w analytics` | Aggregated, event, enrollment, outlier-detection, and tracked-entity analytics + table rebuild |
| `d2w user` | List / get / me / invite / reinvite / reset-password |
| `d2w user-group` / `d2w user-role` | Membership + authority administration |
| `d2w route` | Integration routes (`/api/routes`) — register, run, inspect |
| `d2w maintenance` | Background tasks, cache clear, data-integrity, soft-delete cleanup, validation-rule runs, predictor runs, analytics-table refresh |
| `d2w files` | `/api/documents` + `/api/fileResources` — upload / download / list binary attachments |
| `d2w messaging` | `/api/messageConversations` — send, reply, list, mark read/unread |
| `d2w apps` | `/api/apps` + `/api/appHub` — install / uninstall / update installed apps, browse the App Hub catalog, point DHIS2 at a custom App Hub |
| `d2w fhir` | FHIR Implementation Guide generation, serving, capture and forwarding — the [`dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) pack, only registers when the `[fhir]` extra is installed; without it, `d2w fhir` prints the install command |
| `d2w doctor` | One-command preflight — ~100 metadata-health + integrity checks against a live instance |
| `d2w browser` | Playwright-driven UI automation (PAT minting, dashboard / viz / map screenshot capture, automated OIDC login) — only registers when the `[browser]` extra is installed |
| `d2w dev` | Codegen, UID gen, PAT / OAuth2 seed helpers, branding (`dev customize`), sample data |

Full per-command reference: `d2w --help` (or `uvx --from dhis2w-cli d2w --help` — the package is `dhis2w-cli` but the binary is `d2w`, so `uvx --from` is required).

## Working on the workspace itself

```bash
git clone git@github.com:winterop-com/dhis2w.git
cd dhis2w

make install      # sync workspace deps, and build the capture UI where pnpm is installed
make lint         # ruff + mypy + pyright
make test         # pytest across all members
make docs-serve   # local mkdocs-material

# Bring up a fully-seeded DHIS2 v43 on :8080 (Flyway-bootstraps; v42 still has a seeded e2e dump)
make dhis2-run

# Refresh codegen against the public play instances (no docker needed)
make dhis2-codegen-play
```

## Connecting to a DHIS2 instance

See [`docs/guides/connecting-to-dhis2.md`](docs/guides/connecting-to-dhis2.md) for the full end-to-end walkthrough covering Basic, PAT, and OAuth2/OIDC — including the `dhis.conf` keys the OAuth2 path needs on the DHIS2 server, manual OAuth2 client registration without the seed script, the `openId` user field, and a troubleshooting matrix of every failure mode.

## Documentation + examples

- Architecture + plugin walkthroughs: `docs/architecture/`
- API reference (mkdocstrings-rendered): `docs/api/`
- Releasing: [`docs/releasing.md`](docs/releasing.md)
- Roadmap: [`docs/roadmap.md`](docs/roadmap.md)
- Upstream DHIS2 quirks we've tripped over: [`BUGS.md`](BUGS.md)
- Runnable examples: [`examples/`](examples/README.md) — [`examples/cli/`](examples/cli/) and [`examples/client/`](examples/client/); the MCP examples live in the [`dhis2w-mcp` repository](https://github.com/winterop-com/dhis2w-mcp/tree/main/examples) and the FHIR examples in the [`dhis2w-fhir` repository](https://github.com/winterop-com/dhis2w-fhir/tree/main/examples). One copy of each example, running against v41, v42, v43, and v44 alike; an example that exists for a single major lives under that major's subdirectory — [`examples/client/v43/`](examples/client/v43/) for the v43 schema divergences (`removed_resources.py`, `section_user_removed.py`, `category_combo_coc_regen.py`, …; see [`docs/architecture/schema-diff-v41-v42-v43.md`](docs/architecture/schema-diff-v41-v42-v43.md)) and [`examples/client/v41/`](examples/client/v41/) for the v41 wire quirks (`oauth2_cid_field.py`, `grid_rows_wire_shape.py`, `apps_display_name.py`).

Hard requirements, conventions, and the plugin / auth / workspace model are documented in `CLAUDE.md` and the `docs/` site.
