# Workspace layout

The repo is a `uv` workspace with a virtual root (the root `pyproject.toml` has no `[project]`, only `[tool.uv.workspace]`). Every shippable unit of code is its own member under `packages/`.

## Why a workspace instead of one package

Three reasons:

- **`dhis2w-client` has to be publishable on its own.** A single-package layout would force PyPI users of the client to pull in Typer, FastMCP, Playwright — none of which they need. A workspace lets us ship the client lean.
- **CLI and MCP shouldn't be the same install.** A server running `dhis2w-mcp` in a Docker image doesn't need the CLI's Typer tree. A developer running `d2w` locally doesn't need the MCP stdio loop. The MCP surface is the [`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) plugin pack, in a repository of its own, and builds on `dhis2w-core` like the CLI does.
- **New surfaces land cleanly.** A new surface is a new member or a plugin pack in a repository of its own, not a conditional import inside an existing package. The FHIR Implementation Guide tooling is the worked example: the [`dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) pack splits the generator from the FastAPI facade behind `d2w fhir serve`, so an install that only generates stays free of FastAPI and uvicorn, and the CLI reaches either through an optional extra.

## Layout

```
dhis2w/
├── pyproject.toml                # virtual workspace root + shared tool config
├── uv.lock                       # single workspace-wide lock
├── Makefile                      # drives install/lint/test/docs/build/publish
├── mkdocs.yml                    # docs config (claude theme, left-side nav)
├── CLAUDE.md                     # non-negotiable project rules
├── docs/                         # this site's source
├── site/                         # mkdocs output (gitignored)
├── examples/
└── packages/
    ├── dhis2w-client/             # httpx2 + pydantic lib + Profile + open_client (PAT/Basic/session) (PyPI)
    ├── dhis2w-core/               # TOML profile resolution + OAuth2 token store + plugin runtime + plugins (PyPI)
    ├── dhis2w-cli/                # Typer console script `d2w` (PyPI)
    └── dhis2w-codegen/            # generator — registers `d2w dev codegen` subcommand (workspace-only)
```

The plugin packs live in repositories of their own: [`dhis2w-mcp`](https://github.com/winterop-com/dhis2w-mcp) (the `dhis2w-mcp` server, `dhis2w-mcp-bridge`, and `dhis2w-mcp-router`), [`dhis2w-fhir`](https://github.com/winterop-com/dhis2w-fhir) (`dhis2w-fhir`, `dhis2w-fhir-serve`, and `dhis2w-fhir-engine`), [`dhis2w-browser`](https://github.com/winterop-com/dhis2w-browser), and [`dhis2w-security`](https://github.com/winterop-com/dhis2w-security).

## Configuration split

All lint/type/test tooling (ruff, mypy, pyright, pytest, coverage) is configured **once** at the workspace root. Members inherit these settings automatically — no per-member `ruff.toml` or duplicated mypy stanzas.

Each member's `pyproject.toml` has just:

- `[project]` — name, version, description, Python floor, dependencies
- `[project.scripts]` — console entrypoints (`d2w` from `dhis2w-cli`, for example)
- `[project.entry-points."dhis2w.plugins.v1"]` — plugin registration (what each plugin pack declares)
- `[build-system]` — `uv_build` backend

## Build + publish

`make build` produces wheels for all members. PyPI publishing is automated — tag a `vX.Y.Z` and `.github/workflows/pypi-publish.yml` builds + uploads every publishable member via PyPI Trusted Publishing (OIDC). Three members ship: `dhis2w-client`, `dhis2w-core`, and `dhis2w-cli`. The plugin packs publish their own packages from their own repositories, at the same version, after this workspace. One stays workspace-only: `dhis2w-codegen`, a developer tool that emits committed code into `dhis2w-client`'s tree. See [Releasing to PyPI](../releasing.md) for the full bump-and-tag flow.

## Open questions

- **Docs per-member or one site?** Currently one site. If per-member doc surfaces grow significantly, we may split to one mkdocs config per member stitched together, but starting unified is simpler.
