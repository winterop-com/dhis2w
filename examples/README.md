# dhis2-utils examples

```
examples/
  cli/                              # d2w ... Typer CLI, one script per topic
  client/                           # dhis2w-client Python library
  plugin-external/                  # a third-party plugin registered via entry points
```

## FHIR

The `d2w fhir` examples - the CLI scripts, the Python library, the evaluation engine, and nine
complete example guides - live with the FHIR toolchain in the
[`dhis2w-fhir` repository's `examples/`](https://github.com/winterop-com/dhis2w-fhir/tree/main/examples), documented at <https://winterop-com.github.io/dhis2w-fhir/>.

## The surfaces

| Surface | Best for | Auth handling |
| --- | --- | --- |
| [`client/`](client/) - `dhis2w-client` library | Your own Python tooling; scripts in-process | You pass `AuthProvider` explicitly (Basic, PAT, OAuth2) - no profile layer |
| [`cli/`](cli/) - `d2w <cmd>` | Day-to-day dev, pipelines, human use | Reads `~/.config/dhis2/profiles.toml` + env; `d2w profile add/login` manages creds |
| [`examples/`](https://github.com/winterop-com/dhis2w-mcp/tree/main/examples) of the [`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) pack - `dhis2w-mcp` | Agents, automation over the MCP protocol | Same profile layer as the CLI; every CLI command has a matching MCP tool |

The MCP examples live in the `dhis2w-mcp` repository, beside the MCP server. All three hit DHIS2 through `Dhis2Client`. Pick the shape that fits your caller. See
[Workspace layout](../docs/architecture/workspace.md) for the dependency arrows.

## What every example must be

Two rules, and a new example meets both or it does not land:

1. **Small, self-contained, and about one feature.** A reader opens a file to learn one thing.
   A script that sets up a fixture, exercises four commands, and tears the fixture down teaches
   nobody the second thing it does.
2. **Verified by `make verify-examples`.** An example nobody runs is an example nobody knows still
   works. `infra/scripts/verify_examples.py` executes the whole tree against a seeded stack; an
   entry that genuinely cannot run in a batch pass goes in that script's `SKIP_BY_DEFAULT` with the
   reason stated beside it - "needs a human", "blocks forever", "writes to the instance" - and that
   reason is a gap to close, not a resting place.

`make check-examples` is the static half: every `d2w` command an example invokes resolves in the
Typer tree, and every example path an example mentions exists.

## DHIS2 majors

**One copy of each example, and it runs on v41, v42, and v43.** The wire is the same for almost
everything the examples touch, so a version-neutral file is the honest default.

- CLI examples name no major at all.
- Client examples that need a version-pinned import are written against **v43, the canonical
  baseline**, and carry one comment saying to swap `.v43` for `.v41` / `.v42` to pin another major.
  Most examples do not need the pin: `dhis2w_core.client_context.open_client(profile)` detects the
  major from `/api/system/info` and dispatches accessors at runtime.
- An example that exists **only** for one major lives under that major's subdirectory -
  [`client/v41/`](client/v41/) for v41 wire quirks, [`client/v43/`](client/v43/) for v43 schema
  changes and their workarounds. `make verify-examples` runs the active major's variants and
  ignores the others.

The per-resource schema differences are at
[`docs/architecture/schema-diff-v41-v42-v43.md`](../docs/architecture/schema-diff-v41-v42-v43.md).

## Running

```bash
make dhis2-run DHIS2_VERSION=v42        # foreground DHIS2 + seeded auth (Ctrl+C stops)
# second terminal:
set -a; source infra/home/credentials/.env.auth; set +a

uv run python examples/client/whoami.py
bash examples/cli/whoami.sh
```

Swap `v42` for `v41` or `v43` to boot another stack; the same example files run against all three.
`make refresh-and-verify DHIS2_VERSION=v43` reseeds a v43 instance and runs the whole suite over it.

> **Canonical catalogue**: [`docs/examples.md`](../docs/examples.md) is the curated index - the
> headline examples per topic with links to the concept docs that explain each one. It is not
> exhaustive; `ls examples/{cli,client}/` is the source of truth for what is on disk.

## Environment

- `DHIS2_URL` - default `http://localhost:8080`
- `DHIS2_PAT` - a Personal Access Token
- `DHIS2_USERNAME`, `DHIS2_PASSWORD` - Basic auth fallback
- `DHIS2_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` / `_SCOPES` - for the OIDC examples
- `DHIS2_PROFILE` - pick a named profile from `profiles.toml` without hardcoding credentials
- `DHIS2_VERSION` - `v41`, `v42`, or `v43` - which stack `make dhis2-run` boots, and which major's
  variant directory `verify_examples` adds to the common set
