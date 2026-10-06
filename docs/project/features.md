---
title: Feature catalog
---

# Feature catalog

A complete Python toolkit for DHIS2 v41, v42, v43, and v44 (preview); async client library,
CLI, and codegen, organized as a `uv` workspace with three publishable packages
and a workspace-only generator. The MCP servers
([`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp)), browser automation
([`dhis2w-browser`](https://github.com/winterop-com/dhis2w-browser)), and the FHIR
IG toolchain with its serving facade and evaluation engine
([`dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir)) are plugin packs in
repositories of their own, catalogued here beside the rest.

!!! note "Scope of this page"
    This is the user-facing capability inventory across all surfaces. The exact
    command and tool counts are regenerated per release; the auto-built
    [CLI reference](../cli-reference.md) and [MCP tool reference](https://winterop-com.github.io/dhis2w-mcp/tool-reference/)
    are the source of truth when a number here drifts. For where the project is
    heading, see the [Roadmap](../roadmap.md).

---

## Table of Contents

- [Client Library (dhis2w-client)](#client-library)
- [Plugin Runtime (dhis2w-core)](#plugin-runtime)
- [Command-Line Interface (dhis2w-cli)](#command-line-interface)
- [MCP Server (the dhis2w-mcp pack)](#mcp-server)
- [MCP CLI Bridge (the dhis2w-mcp pack)](#mcp-cli-bridge)
- [MCP Router (the dhis2w-mcp pack)](#mcp-router)
- [Browser Automation (dhis2w-browser)](#browser-automation)
- [FHIR (the dhis2w-fhir pack)](#fhir)
- [Code Generator (dhis2w-codegen)](#code-generator)
- [Cross-Cutting Capabilities](#cross-cutting-capabilities)

---

## Client Library

**Package:** `dhis2w-client` | **Install:** `uv add dhis2w-client`

Pure async httpx2 + pydantic DHIS2 API client. Zero dependency on the plugin
runtime; drop it into any async Python project.

### Authentication Providers

| Provider | Mechanism | Token Storage |
| --- | --- | --- |
| **Basic** | HTTP Basic (username/password, Base64) | None |
| **PAT** | Personal Access Token (`ApiToken` header) | None |
| **OAuth2/OIDC** | Authorization-code flow with PKCE against `/oauth2/authorize` and `/oauth2/token` | SQLite (`tokens.sqlite`) with auto-refresh |

All three implement the `AuthProvider` protocol. Custom providers (service-account
JWT, OIDC federation, proxy-injected headers) can be added by implementing the
same protocol without touching the client.

### Generated Type System

Two codegen pipelines feed typed models into the client:

- **`/api/schemas`**: pydantic models + `StrEnum`s for every metadata resource
  (DataElement, Indicator, Program, OrgUnit, ...)
- **`/api/openapi.json`**: instance-side shapes (tracker write payloads,
  response envelopes, auth scheme discriminators)

Each DHIS2 version (v41, v42, v43, v44) has its own generated tree under
`dhis2w_client.generated.v{N}/`. One wire shape is hand-written beside the
generated tree: `MapView` and its three enums live in `dhis2w_client.v{N}.maps`,
so every tree exposes one shape no matter what a release lists for
`mapView` on `/api/schemas` (DHIS2_ISSUES.md #43).

### Resource Accessors

Auto-generated typed CRUD for every metadata resource:

```python
elements = await client.resources.data_elements.list(filter="name:ilike:malaria")
element = await client.resources.data_elements.get(uid)
await client.resources.data_elements.create(payload)
await client.resources.data_elements.patch(uid, operations)
await client.resources.data_elements.delete(uid)
```

### Domain APIs

| Domain | Methods |
| --- | --- |
| **System** | `me()`, `info()`, `calendar()`, `generate_uids()` |
| **Tracker** | `register()`, `enroll()`, `add_event()`, `outstanding()`; reads `tracked_entities()`, `enrollments()`, `events()` with the standard `/api/tracker` query surface (program, organisation unit and mode, status, field selector, paging, updated-after) |
| **Analytics** | `aggregate()` for a parsed pivot, `event_query()` / `enrollment_query()` for the tracker line lists, `stream()` / `stream_to()` for chunked downloads |
| **Data values** | `stream()` imports JSON / XML / CSV / ADX without buffering, with `atomic_mode`; `export()` reads a form's values back as a typed `DataValueSet`; `import_grouped_by_dataset()` for the v43 mixed-data-set path |
| **Completeness** | `complete_data_set_registrations.export()` reads which forms are reported complete, by data set, period or date range, organisation unit and subtree |
| **Maintenance** | `get_integrity_report()`, `iter_integrity_issues()`, `update_category_option_combos()`, `run_analytics_tables()` |
| **Tasks** | `await_completion()` and `iter_notifications()` block on a background job; `poll_once()` reads its feed once and returns a cursor for the next tick |
| **Apps** | `list()`, `hub_list()`, `install()`, `uninstall()`, `update()` |
| **Files** | `documents()`, `file_resources()`, `upload()`, `download()` |
| **Messaging** | `conversations()`, `send()`, `reply()`, `mark_read()` |
| **Customization** | `logo_front()`, `logo_banner()`, `style()`, `system_setting()` |
| **Maps** | `maps.list_all()`, `get()`, `create_from_spec()` from a `MapSpec` of `MapLayerSpec` layers, `clone()`, `delete()`; every major authors through `/api/metadata`, which is the only path that persists a layer's references (DHIS2_ISSUES.md #114) |

### Bulk Operations

- `patch_bulk(resource_type, patches, concurrency=8)`: RFC 6902 JSON Patch across many UIDs, fanned out through a bounded worker pool
- `apply_sharing_bulk(resource_type, uids, sharing, concurrency=8)`: one sharing block applied to many UIDs through the same pool
- `analytics.stream_to(path, ...)`: stream a large analytics result to disk
- `client.stream(method, path, sink, params=...)`: stream any endpoint's body to a `Path`, a `.write(bytes)` object, or a chunk callable, so an export never sits in memory

### Utilities

- **Period math:** `parse_period()`, `next_period_id()`, `previous_period_id()`, `period_start_end()`
- **UID generation:** `generate_uids(count)`: offline, CSPRNG-based
- **Retry transport:** honors `Retry-After`, retries 429/502/503/504 automatically

---

## Plugin Runtime

**Package:** `dhis2w-core` | **Install:** `uv add dhis2w-core`

Shared runtime that bridges the pure client with user-facing surfaces (CLI, MCP).
Provides profile discovery, plugin registry, auth factory, and token store.

### Profile System

Connection profiles are discovered automatically:

1. `./.dhis2/profiles.toml`: project-local (CWD walk-up)
2. `~/.config/dhis2/profiles.toml`: user-wide
3. Environment variables: `DHIS2_URL`, `DHIS2_USERNAME`/`DHIS2_PASSWORD`/`DHIS2_PAT`
4. `DHIS2_PROFILE` env to pin a named profile

Each profile stores: name, base URL, auth type (basic/pat/oauth2), and DHIS2
version (v41/v42/v43/v44).

### Token Store

SQLite-backed (`aiosqlite`) at `.dhis2/tokens.sqlite`, keyed by profile name,
base URL, and OAuth client id. Handles OAuth2 token caching and automatic
refresh on expiry.

### First-Party Plugins

22 built-in plugins, each with a service layer (`service.py`) and CLI
commands (`cli.py`); most also have MCP tools, which live in the
[`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) pack as
`dhis2w_mcp/tools/v{N}/<plugin>.py` and call the same `service.py`. Every built-in
plugin exists in four version trees (v41, v42, v43, v44). The rows naming a pack -
**fhir**, **security**, **browser** - are plugins from repositories of their own,
mounted through the external entry-point mechanism when the pack is installed.

| Plugin | Domain |
| --- | --- |
| **metadata** | List, get, create, patch, delete all resource types. Bulk import/export, filter DSL, sharing, cross-resource search, usage reverse-lookup, bundle diff/merge across profiles. |
| **schema** | Generated-model introspection: describe any metadata or instance-side type's fields (prefers the OpenAPI tree). |
| **data** | Router to aggregate + tracker subdomains. |
| **aggregate** | Data value fetch, push, set, delete. Bulk import with `importStrategy` and dry-run. |
| **tracker** | Tracked entities, enrollments, events, relationships. Register, enroll, create events, list outstanding follow-ups. |
| **analytics** | Aggregated, event, enrollment, and tracked-entity queries. Outlier detection. |
| **user** | List, get, invite, reinvite, reset-password. Mounts `group` and `role` sub-apps. |
| **user-group** | CRUD + member management + sharing (mounted as `d2w user group`). |
| **user-role** | CRUD + authority grants (mounted as `d2w user role`). |
| **route** | Integration routes: register, run, inspect, delete. Five auth-scheme types. |
| **apps** | List installed, browse App Hub, install from file or hub, uninstall, update with semver picking, snapshot/restore. |
| **datastore** | Key-value store: namespaces, keys, get/set/delete on `/api/dataStore` + `/api/userDataStore`. |
| **files** | Documents + fileResources: upload, download, list. |
| **fhir** | FHIR Implementation Guide generation, serving, capture, and forwarding - the [`dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) pack, installed alongside the CLI with `uv tool install 'dhis2w-cli[fhir]'`. See [FHIR](#fhir). |
| **messaging** | Message conversations: list, get, send, reply, mark read/unread, ticket-workflow priority/status/assignment. |
| **maintenance** | Background tasks, cache clear, data-integrity checks, soft-delete cleanup, validation runs, predictor runs, analytics-table rebuild. |
| **doctor** | Health probes: ~100+ metadata checks, DHIS2 data-integrity checks, DHIS2_ISSUES.md workaround drift detection. |
| **security** | The read-only security posture scanner — version and patch posture, transport and security headers, password policy and registration settings, authority risk categorisation, role and account audits, installed-apps inventory, anonymous-access and default-credential probes, public-metadata sharing, route targets, personal access tokens, external login methods, auditing posture, and a resumable `audit` runner writing Markdown / plaintext / CSV / HTML reports — is the [`dhis2w-security`](https://github.com/winterop-com/dhis2w-security) pack, installed alongside the CLI with `uv tool install 'dhis2w-cli[security]'` (or `uv add dhis2w-security` in a project). |
| **system** | System info, current user (whoami), calendar, system-settings read/write. |
| **customize** | Brand + theme an instance: login logos, banner, CSS, preset apply. |
| **profile** | Profile CRUD, verification, OAuth2 login/logout, OIDC discovery, PAT + OAuth2-client provisioning. |
| **browser** | Playwright-driven UI automation (PAT creation, login, screenshots). Requires `[browser]` extra. |
| **dev** | Developer tools: UID generation, codegen, sample-data fixtures. |

### External Plugin Discovery

A plugin is a plain class with one `@extension` method, `contribute(version_key)`,
returning a `Contribution` that names the plugin and the modules exposing
`register(app)` and `register(server)` for its CLI and MCP surfaces. A pack
advertises that object under the `dhis2w.plugins.v1` entry-point group, and the
pluginkit host in `dhis2w_core.plugin` loads it alongside the built-ins at
startup. A pack that fails to import is reported in `PluginHost.failures`
rather than taking the CLI down; the [`dhis2w-security`](https://github.com/winterop-com/dhis2w-security),
[`dhis2w-browser`](https://github.com/winterop-com/dhis2w-browser), and
[`dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) packs are the first-party examples. `d2w security`, `d2w browser`,
and `d2w fhir` without their pack installed print the `uv tool install "dhis2w-cli[<extra>]"`
command that adds it.

An out-of-repo plugin gets the same test environment from `dhis2w_core.testing`, a pytest
plugin shipped by `dhis2w-core[testing]` and loaded with
`pytest_plugins = ["dhis2w_core.testing"]`.

---

## Command-Line Interface

**Package:** `dhis2w-cli` | **Install:** `uv tool install dhis2w-cli`

Typer console script `d2w` that wraps every plugin as CLI subcommands.

### Command Tree

```
d2w profile         Manage connection profiles
  list | show | default | verify
  add | remove | rename
  bootstrap             One-shot: provision a PAT or OAuth2 client + save a profile
  login | logout        OAuth2 token flows
  oidc-config           Discover a DHIS2 instance's OIDC endpoints into a profile
  pat                   Provision Personal Access Tokens on DHIS2
  oauth2                Manage DHIS2 OAuth2 clients on the server (admin ops)

d2w system          System information
  whoami                Everything DHIS2 reports about the authenticated user
  info                  Server version, build, analytics state
  calendar              Show or change the active calendar
  settings              Read/write DHIS2 system settings

d2w schema          Describe a generated type's fields (metadata or instance-side)

d2w metadata        Metadata inspection + CRUD
  list | get            Browse resources with filters, fields, paging
  search                Cross-resource metadata search
  usage                 Reverse lookup: what references this UID?
  export | import       Bulk metadata bundles (with strategy + dry-run)
  patch | rename | retag
  share                 Apply one sharing block across many UIDs
  diff | diff-profiles | merge

d2w data            Data values
  aggregate get | push | set | delete
  tracker list | get | type | push | delete
  tracker register | enrollment | event | relationship
  tracker outstanding   List outstanding follow-ups

d2w analytics       Analytics queries
  query                 Run an aggregate analytics query
  events | enrollments | tracked-entities
  outlier-detection     Flag statistical anomalies in data values

d2w user            User administration
  list | get | invite | reinvite | reset-password
  group                 User groups (CRUD, members, sharing)
  role                  User roles (CRUD, authority grants)

d2w route           Integration routes
  list | get | create | update | patch | delete
  run                   Execute a route (DHIS2 proxies to the target URL)

d2w apps            App management
  list | add | remove | update | reload
  snapshot | restore    Portable JSON snapshots of installed apps
  hub-list | hub-url    Browse the App Hub / manage its configured URL

d2w datastore       Key-value data store
  namespaces | keys | get | set | delete | delete-namespace

d2w files           File management
  documents list | get | upload | upload-url | download | delete
  resources upload | get | download

d2w fhir            FHIR IG generation, serving, capture and forwarding (the dhis2w-fhir pack,
                    installed with the [fhir] extra)

d2w messaging       Internal messaging
  list | get | send | reply | delete
  mark-read | mark-unread
  set-priority | set-status | assign | unassign

d2w maintenance     System maintenance
  task | cache | cleanup
  dataintegrity         DHIS2 data-integrity checks
  refresh               Regenerate analytics / resource / monitoring tables
  validation | predictors

d2w customize       Brand + theme an instance
  logo-front | logo-banner | style
  apply                 Apply a committed preset directory in one call
  show                  Current /api/loginConfig snapshot

d2w doctor          Health diagnostics
  metadata              ~100+ metadata health checks
  integrity             DHIS2 data-integrity checks
  bugs                  DHIS2_ISSUES.md workaround drift detection

d2w browser         UI automation (requires [browser] extra)
  pat                   Mint a Personal Access Token via Playwright
  dashboard | viz | map Capture workflows (render to PNG)

d2w dev             Developer tools
  uid                   Generate DHIS2 UIDs (offline, CSPRNG)
  sample                Inject known-good fixtures (route, data, pat, oauth2-client)
  codegen generate | fetch-openapi | oas-flips | rebuild | oas-rebuild | diff
```

### Output Modes

- **Default:** Rich formatted tables with color
- **`--json`:** Raw JSON for scripting and piping
- **`--profile <name>`:** Override the active profile for a single command

### Query DSL

Available on all list commands:

```bash
d2w metadata list dataElements \
  --filter 'name:ilike:malaria' \
  --filter 'valueType:eq:NUMBER' \
  --root-junction AND \
  --fields id,name,shortName,valueType \
  --order name:asc \
  --page 1 --page-size 25

# A field transformer replaces a collection with a scalar: how many organisation
# units each data set is assigned to, without pulling the assignments.
d2w metadata list dataSets --fields 'id,name,organisationUnits~size'
```

---

## MCP Server

**Package:** `dhis2w-mcp`, a plugin pack in its own repository
([winterop-com/dhis2w-mcp](https://github.com/winterop-com/dhis2w-mcp), documented at
<https://winterop-com.github.io/dhis2w-mcp/>) | **Install:** `uv tool install dhis2w-mcp`

FastMCP server (`dhis2`) exposing every plugin as typed MCP tools: 315 tools
across 14 plugin groups, plus whatever a plugin pack registers. The tools of the
built-in plugins live in the pack as `dhis2w_mcp/tools/v{N}/<plugin>.py`,
registered through one `mcp` plugin contribution, and call the same core
`service.py` as the CLI. The full catalog is auto-generated into the pack's
[tool reference](https://winterop-com.github.io/dhis2w-mcp/tool-reference/).

### Tool Naming

Snake-case, verb-last: `<plugin>_<resource>_<verb>`

```
metadata_attribute_find
data_aggregate_get
analytics_enrollments_query
user_group_add_member
system_calendar_set
maintenance_cache_clear
doctor_integrity
```

### Supported Hosts

| Host | Configuration |
| --- | --- |
| **Claude Desktop** | `claude_desktop_config.json` |
| **Claude Code** | `claude mcp add dhis2 -s user -- ...` |
| **Cursor** | `~/.cursor/mcp.json` |
| **Generic** | Any stdio-based MCP client |

### Transport

Stdio transport. Lazy plugin discovery on startup. Tool names, descriptions, and
schemas auto-derived from function signatures and docstrings.

### Errors an MCP caller can act on

A tool that fails on the profile or on reaching the instance answers with the
text the CLI prints for the same failure, hint block included - one middleware,
one source of truth in `dhis2w_core`:

- **No profile configured** names `d2w profile add <name>` and
  `d2w profile bootstrap`.
- **An instance nothing answers at** names the URL that was dialled and the two
  next steps: check the profile's `base_url`, and `d2w profile show <name>` to
  see it. A bare transport string tells an agent neither which instance it tried
  nor what to do about it.

---

## MCP CLI Bridge

**Package:** `dhis2w-mcp-bridge`, from the `dhis2w-mcp` plugin pack
([winterop-com/dhis2w-mcp](https://github.com/winterop-com/dhis2w-mcp)) | **Install:** `uv tool install dhis2w-mcp-bridge`

FastMCP server (`dhis2w-mcp-bridge`) that exposes the whole `d2w` CLI as a
single `dhis2_cli` tool: one tool schema instead of ~313, sized for small
local models (LM Studio, Ollama, llama.cpp) that drive it by progressive
`--help` discovery. Supports a read-only mode via `DHIS2_MCP_READONLY=1`.
Use the full `dhis2w-mcp` server for capable cloud models; the design
rationale lives in the pack's
[bridge design](https://winterop-com.github.io/dhis2w-mcp/architecture/mcp-bridge/).

---

## MCP Router

**Package:** `dhis2w-mcp-router`, from the `dhis2w-mcp` plugin pack
([winterop-com/dhis2w-mcp](https://github.com/winterop-com/dhis2w-mcp)) | **Install:** `uv tool install dhis2w-mcp-router`

Domain-neutral MCP router: it fronts many upstream MCP servers behind two
meta-tools, search and dispatch, so an agent gets lazy, searchable tool
discovery instead of the whole tool payload up front. The design lives in the
pack's [router design](https://winterop-com.github.io/dhis2w-mcp/architecture/mcp-router/),
and the [surfaces comparison](https://winterop-com.github.io/dhis2w-mcp/architecture/mcp-surfaces/)
sets it beside the full server and the bridge.

---

## Browser Automation

**Package:** `dhis2w-browser`, a plugin pack in its own repository
([winterop-com/dhis2w-browser](https://github.com/winterop-com/dhis2w-browser), documented at
<https://winterop-com.github.io/dhis2w-browser/>) | **Install:** `uv tool install 'dhis2w-cli[browser]'`, or
`uv add dhis2w-browser` for the library alone

Playwright-based DHIS2 UI automation, together with the `d2w browser` plugin. It lives outside
this repository so API-only installs never pull Chromium.

### Library API

| Function | Purpose |
| --- | --- |
| `logged_in_page()` | Async context manager returning a `(BrowserContext, Page)` logged into DHIS2 |
| `session_from_cookie()` | Fast-path: inject a pre-minted `JSESSIONID` cookie |
| `create_pat()` | Mint a Personal Access Token through a browser session (DHIS2 returns the token value only once) |
| `drive_oauth2_login()` | Full OIDC flow via Chromium: authorize URL, React login, Spring AS consent, loopback redirect |
| `drive_login_form()` | Lower-level: navigate to authorize URL, fill login + consent, wait for redirect |
| `capture_dashboard()` | Render a dashboard to PNG |
| `capture_visualization()` | Render a visualization to PNG |
| `capture_map()` | Render a map to PNG |

### Display Modes

- **Headless** (default for automation): no visible browser window
- **Headful** (`DHIS2_HEADFUL=1` or `--headful`): visible browser for debugging

### Why Browser?

- PAT creation requires a session cookie: DHIS2 gates `/api/apiToken` behind it
- OAuth2 login requires driving the React login form and Spring Authorization
  Server consent screen
- Dashboard/visualization/map rendering requires the full DHIS2 web app

---

## FHIR

**Packages:** `dhis2w-fhir`, `dhis2w-fhir-serve`, `dhis2w-fhir-engine`, the `dhis2w-fhir` plugin pack in its own repository
([winterop-com/dhis2w-fhir](https://github.com/winterop-com/dhis2w-fhir), documented at <https://winterop-com.github.io/dhis2w-fhir/>) |
**Install:** `uv tool install "dhis2w-cli[fhir]"`, or `"dhis2w-cli[fhir,serve]"` for the serving facade

Turn a DHIS2 instance into a published FHIR R4 Implementation Guide, serve that guide as a read-and-capture
facade, and drain what was captured back into DHIS2 (`d2w fhir init`, `generate`, `validate`, `serve`,
`forward`, `doctor`), with a FHIRPath, CQL, and quality-measure evaluation engine beneath it. The pack registers
`d2w fhir` through the `dhis2w.plugins.v1` entry point. Without it installed, `d2w fhir` prints the install command
above. The full catalog is in the pack's [documentation](https://winterop-com.github.io/dhis2w-fhir/).

---

## Code Generator

**Package:** `dhis2w-codegen` | **Workspace-only** (not published to PyPI)

Version-aware generator that emits typed Python code into `dhis2w-client`.

### Pipelines

| Pipeline | Source | Output |
| --- | --- | --- |
| **Schemas** | `/api/schemas` on a live DHIS2 instance | Pydantic models + `StrEnum`s for every metadata resource |
| **OpenAPI** | `/api/openapi.json` on a live DHIS2 instance | Instance-side shapes (tracker writes, envelopes, auth schemes) |

### Commands

```bash
d2w dev codegen generate --url <DHIS2> --username <u> --password <p>
d2w dev codegen fetch-openapi --url <DHIS2> --username <u> --password <p>
d2w dev codegen rebuild          # regenerate from committed manifest
d2w dev codegen oas-rebuild      # re-emit OpenAPI-based types
d2w dev codegen oas-flips <a> <b> # pointers that differ between captures of one release
d2w dev codegen diff <from> <to> # structural diff between versions
```

### Architecture

- `discover.py`: fetch `/api/schemas`, normalize to `SchemasManifest`
- `emit.py`: walk manifest, render pydantic models via Jinja templates
- `oas_emit.py`: emit OpenAPI-based shapes with spec patches
- `spec_patches.py`: apply fixes for things DHIS2's OpenAPI spec omits
- `diff.py`: cross-version structural diff (e.g., v42 vs v43)

---

## Cross-Cutting Capabilities

### Multi-Version Support

Four DHIS2 major versions (v41, v42, v43, v44) are supported with separate
plugin trees and generated code. v44 is a preview: 2.44.0 is not released, so
the v44 tree and its generated code target a 2.44 development build pinned by
digest, and the v44 end-to-end CI leg does not gate a merge (see
[Versioning](../architecture/versioning.md)). The supported set is the `Dhis2`
enum in `dhis2w_client.generated`. Version resolution:

1. `profile.version` field in `profiles.toml`
2. `DHIS2_VERSION` environment variable
3. Default: `v43`

`d2w --version` shows which plugin tree booted and where the version came from.

### Async-First Architecture

Every client method is async. The entire runtime uses `async/await` with `httpx2`
as the HTTP transport.

```python
async with Dhis2Client(base_url, auth=PatAuth(token)) as client:
    me = await client.system.me()
    elements = await client.resources.data_elements.list()
```

### Three-Surface Plugin Model

Every feature ships as a plugin with three surfaces sharing one service layer:

```
plugin/
  service.py   <-- async business logic (shared)
  cli.py       <-- Typer commands
  models.py    <-- pydantic view-models
  tests/       <-- pytest suite
```

The FastMCP tool definitions for a plugin live in the
[`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) pack as
`dhis2w_mcp/tools/v{N}/<plugin>.py`, calling the same `service.py`.
Adding a new plugin wires it into the CLI; its MCP tools land in the pack.

### Pydantic Everywhere

All structured data uses `pydantic.BaseModel`. No raw dicts cross module
boundaries. No dataclasses. DHIS2 resource models, service return values, CLI
output shapes, MCP tool returns, error bodies, and configuration are all typed.

### Metadata Query DSL

Available across CLI, MCP, and library:

- Multi-filter with OR/AND junction
- Field selector (equivalent to DHIS2's `fields=` parameter), including the
  field transformers `~size`, `~isEmpty`, `~isNotEmpty` and `~rename(...)`
- Multi-column ordering
- Paging with page/page-size

### Health and Diagnostics

`d2w doctor` runs ~100+ metadata health checks, DHIS2's own data-integrity
checks, and DHIS2_ISSUES.md workaround drift detection. Available via CLI and MCP.

### Examples

One example tree, version-neutral: each example is a single copy that runs
against DHIS2 v41, v42, v43, and v44.

- **`examples/client/`**: 80+ Python examples (whoami, CRUD, analytics, OIDC,
  bulk import, tracker lifecycle, sharing, error handling, ...)
- **`examples/cli/`**: 60+ shell scripts covering every CLI domain
- **MCP examples**: 40+ Python examples showing MCP tool usage, in the
  [`dhis2w-mcp` repository's `examples/`](https://github.com/winterop-com/dhis2w-mcp/tree/main/examples)
- **FHIR examples**: the `d2w fhir` scripts, the library examples, and the example guides, in the
  [`dhis2w-fhir` repository's `examples/`](https://github.com/winterop-com/dhis2w-fhir/tree/main/examples)

Examples that exist for one major only live under that major's subdirectory -
`examples/client/v41/` (3 v41 wire quirks) and `examples/client/v43/`
(10 v43 schema divergences). v44 also runs the `examples/client/v43/` variants,
since 2.44 ships the same v43 features. Every example is small, shows one feature, and is
executed by `make verify-examples`.

---

## Dependency Graph

```
dhis2w-cli --------> dhis2w-core ------> dhis2w-client
dhis2w-mcp --------> dhis2w-core    (the dhis2w-mcp pack, own repository)

dhis2w-cli ..(optional [browser] / [security] extras)..> the dhis2w-browser and
              dhis2w-security packs, each in its own repository

dhis2w-cli ..(optional [fhir] / [serve] extras)..> the dhis2w-fhir pack (dhis2w-fhir,
              dhis2w-fhir-serve, dhis2w-fhir-engine), in its own repository

dhis2w-codegen        workspace-only generator
```

No dependency cycles. `dhis2w-client` is standalone, and every plugin pack is
optional.

