.PHONY: help install lint check-examples test test-slow test-contract test-durations coverage docs docs-serve docs-build docs-cli build publish-all deps-upgrade clean clean-artifacts dhis2-run dhis2-down dhis2-seed dhis2-versions-check dhis2-versions-bump dhis2-build-e2e-dump dhis2-migrate-e2e-dump dhis2-codegen-all dhis2-codegen-play dhis2-codegen-play-v41 dhis2-codegen-play-v42 dhis2-codegen-play-v43 verify-examples refresh-setup refresh-and-verify

UV := $(shell command -v uv 2> /dev/null)

# Silence Material for MkDocs' "Currently unlicensed" / MkDocs 2.0 build notice.
# https://squidfunk.github.io/mkdocs-material/blog/2026/02/18/mkdocs-2.0/
export NO_MKDOCS_2_WARNING := 1

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Development:"
	@echo "  install          Sync workspace deps (all members, dev group included)"
	@echo "  lint             Run ruff format + ruff check + mypy + pyright"
	@echo "  test             Run tests (excludes slow)"
	@echo "  test-slow        Run slow tests only"
	@echo "  test-contract    Run live-schema contract tests against play.im.dhis2.org"
	@echo "  test-durations   Show 20 slowest tests"
	@echo "  coverage         Run tests with coverage reporting"
	@echo "  build            Build all workspace wheels"
	@echo "  publish-<member> Build + upload one dhis2w-<member> to PyPI (requires UV_PUBLISH_TOKEN env)"
	@echo "                   Members: $(PUBLISHABLE_MEMBERS)"
	@echo "                   VERSION=X.Y.Z asserts the package's pyproject version before building"
	@echo "  publish-all      Upload every publishable member in dependency order (same token)"
	@echo "                   VERSION=X.Y.Z asserts every member's pyproject version before building"
	@echo "  deps-upgrade     Re-resolve uv.lock to pick up newer versions"
	@echo "  clean            Remove caches, build artifacts, coverage output, and run artifacts"
	@echo "  clean-artifacts  Remove run artifacts alone: reports, screenshots, browser and property-test state"
	@echo ""
	@echo "Docs:"
	@echo "  docs             Alias for docs-serve"
	@echo "  docs-serve       Serve mkdocs site locally at http://127.0.0.1:8000 (regens CLI ref first)"
	@echo "  docs-build       Build mkdocs site to ./site (regens CLI ref first)"
	@echo "  docs-cli         Regenerate docs/cli-reference.md from the Typer app"
	@echo ""
	@echo "DHIS2 local stack:"
	@echo "  dhis2-run        Start the stack, seed auth, stream logs (Ctrl+C tears it down)"
	@echo "  dhis2-seed       (re-)seed PATs + OAuth2 client against an already-running stack"
	@echo "  dhis2-down       Stop the local DHIS2 stack"
	@echo "  dhis2-versions-check  Show whether any pinned DHIS2 minor is behind the latest Docker Hub patch"
	@echo "  dhis2-versions-bump   Rewrite versions.env to the latest patch for each non-held minor (then regenerate codegen)"
	@echo "  dhis2-build-e2e-dump  Wipe + populate a fresh DHIS2 with test data, regenerate infra/\$$(DHIS2_VERSION)/dump.sql.gz"
	@echo "  dhis2-migrate-e2e-dump  Restore the committed dump into the pinned image, let DHIS2 migrate it, dump it back (pin bumps)"
	@echo "  refresh-setup         Wipe + rebuild e2e dump + seed (no example verify — fast iteration on setup)"
	@echo "  refresh-and-verify    Rebuild dump + seed + refresh analytics + run every example"
	@echo ""
	@echo "Code generation + examples:"
	@echo "  dhis2-codegen-all     Spin up DHIS2 v41/v42/v43/v44 in turn and regenerate each v{N}/ (pass VERSIONS=\"v43 v44\" to narrow)"
	@echo "  dhis2-codegen-play    Refresh the /api/schemas half of generated/v{N} from the play channel running each pin (no docker)"
	@echo "  verify-examples       Run every non-interactive example + print PASS/FAIL summary"
	@echo ""
	@echo "  For niche targets (versions, wait, status, logs, pat) use 'make -C infra help'."

install:
	@echo ">>> Syncing workspace"
	@$(UV) sync --all-packages --all-extras

lint:
	@echo ">>> Running linter"
	@$(UV) run ruff format .
	@$(UV) run ruff check . --fix
	@echo ">>> Running type checkers"
	@$(UV) run mypy --explicit-package-bases packages examples infra/scripts
	@$(UV) run pyright

check-examples:
	@echo ">>> Checking example paths resolve (no per-version tree, no dangling references)"
	@$(UV) run python -u infra/scripts/check_example_paths.py
	@echo ">>> Checking example CLI commands + MCP tool references resolve"
	@$(UV) run python -u infra/scripts/check_example_refs.py

test:
	@echo ">>> Running tests (excluding slow + contract)"
	@$(UV) run pytest -n auto -q -m "not slow and not contract" packages

test-contract:
	@echo ">>> Running live-schema contract tests against play.im.dhis2.org"
	@$(UV) run pytest -v -m contract packages

test-upstream-bugs:
	@echo ">>> Running upstream-bug regression tests (paired with BUGS.md entries)"
	@$(UV) run pytest -v -m upstream_bug packages

test-slow:
	@echo ">>> Running slow tests"
	@if [ -f infra/home/credentials/.env.auth ]; then \
		set -a; . infra/home/credentials/.env.auth; set +a; \
		$(UV) run pytest -v -m slow packages; \
	else \
		echo "    (no infra/home/credentials/.env.auth — integration tests that need it will skip; run 'make dhis2-run' first to populate it)"; \
		$(UV) run pytest -v -m slow packages; \
	fi

test-durations:
	@echo ">>> Running tests with 20 slowest"
	@$(UV) run pytest -q -m "not slow and not contract" --durations=20 packages

coverage:
	@echo ">>> Running tests with coverage"
	@$(UV) run pytest -n auto -q -m "not slow and not contract" \
		--cov --cov-report=term-missing --cov-report=xml --cov-fail-under=70 packages

# The reference docs render the canonical v43 surface (CLAUDE.md baseline). Pin the
# version so the output is reproducible everywhere — CI (no profile) and local dev
# (any active profile) alike. The sentinel DHIS2_PROFILE makes profile resolution
# miss, so DHIS2_VERSION wins instead of whatever .dhis2 profile happens to be active.
DOCS_DHIS2_VERSION ?= v43
DOCS_PIN := DHIS2_PROFILE=__docs_no_profile__ DHIS2_VERSION=$(DOCS_DHIS2_VERSION)

docs-cli:
	@echo ">>> Regenerating CLI reference from the Typer app (pinned to $(DOCS_DHIS2_VERSION))"
	@$(DOCS_PIN) $(UV) run typer dhis2w_cli.main utils docs --name d2w --title "CLI reference" --output docs/cli-reference.md
	@echo "    wrote docs/cli-reference.md"

docs-serve: docs-cli
	@echo ">>> Serving docs at http://127.0.0.1:8000"
	@$(UV) run mkdocs serve

docs-build: docs-cli
	@echo ">>> Building docs site (strict — broken links / missing nav fail the build)"
	@$(UV) run mkdocs build --strict

docs: docs-serve

build:
	@echo ">>> Building all workspace wheels"
	@$(UV) build --all-packages

# Releasing from the terminal. The other path to PyPI is a tag: push vX.Y.Z and
# .github/workflows/pypi-publish.yml builds and uploads every dhis2w-* package
# via Trusted Publishing, which needs no token. These targets need
# UV_PUBLISH_TOKEN and upload from the checkout in front of you.
#
# The publishable workspace members, in dependency order: each one is uploaded
# after everything it imports, so a resolver reading PyPI mid-release never meets
# a package naming a sibling version the index has not seen yet. The workspace-only
# member dhis2w-codegen is absent on purpose: it is an internal tool with nothing
# to offer a PyPI consumer.
#
# Names here are the suffix after `dhis2w-`; the targets are `publish-<suffix>`.
PUBLISHABLE_MEMBERS := client core cli

# The release version, when the caller names one: `make publish-all VERSION=1.2.0`
# asserts every member's `project.version` equals it before anything is built,
# the same check .github/workflows/pypi-publish.yml runs against the tag. Left
# unset, the targets upload whatever version the checkout carries.
VERSION ?=

# `publish-<member>` is deliberately not declared .PHONY: GNU make skips pattern-rule
# search for a phony target, and the pattern rule below is the whole family. Nothing
# in the tree is named `publish-anything`, so there is no file for it to collide with.
#
# One member: build its wheel + sdist and upload that pair alone. The member's
# own artifacts are removed from dist/ first, so a dist/ holding an earlier
# version cannot be uploaded alongside the one just built — `make build` and the
# sibling publish targets all write into the same directory.
publish-%:
	@test -n "$(UV_PUBLISH_TOKEN)" || { \
		echo "UV_PUBLISH_TOKEN is unset — export a PyPI token before publishing dhis2w-$*"; \
		exit 2; \
	}
	@if [ -n "$(VERSION)" ]; then \
		file="packages/dhis2w-$*/pyproject.toml"; \
		file_version=$$($(UV) run --no-project python -c "import sys, tomllib; print(tomllib.load(open(sys.argv[1], 'rb'))['project']['version'])" "$$file"); \
		if [ "$$file_version" != "$(VERSION)" ]; then \
			echo "dhis2w-$*: $$file says $$file_version, the release names $(VERSION) — bump the package or fix VERSION"; \
			exit 1; \
		fi; \
		echo ">>> dhis2w-$*: pyproject version $$file_version matches VERSION"; \
	fi
	@echo ">>> Building dhis2w-$* wheel + sdist"
	@rm -f dist/$(subst -,_,dhis2w-$*)-*.whl dist/$(subst -,_,dhis2w-$*)-*.tar.gz
	@$(UV) build --package dhis2w-$*
	@echo ">>> Uploading dhis2w-$* to PyPI"
	@$(UV) publish dist/$(subst -,_,dhis2w-$*)-*.whl dist/$(subst -,_,dhis2w-$*)-*.tar.gz

publish-all:
	@test -n "$(UV_PUBLISH_TOKEN)" || { \
		echo "UV_PUBLISH_TOKEN is unset — export a PyPI token before publishing"; \
		exit 2; \
	}
	@echo ">>> Publishing every dhis2w-* package in dependency order:"
	@echo "    $(PUBLISHABLE_MEMBERS)"
	@for member in $(PUBLISHABLE_MEMBERS); do \
		$(MAKE) --no-print-directory publish-$$member VERSION="$(VERSION)" || exit 1; \
	done
	@echo ">>> Every member uploaded"

deps-upgrade:
	@echo ">>> Upgrading all resolvable deps (uv lock --upgrade)"
	@$(UV) lock --upgrade
	@echo ">>> Re-syncing workspace with updated lock"
	@$(UV) sync --all-packages --all-extras

dhis2-run:
	@DHIS2_VERSION=$(or $(DHIS2_VERSION),v43) infra/scripts/dhis2_run.sh

dhis2-seed:
	@$(MAKE) -C infra seed

dhis2-down:
	@$(MAKE) -C infra down

dhis2-build-e2e-dump:
	@$(MAKE) -C infra build-e2e-dump DHIS2_VERSION=$(or $(DHIS2_VERSION),v43)

dhis2-migrate-e2e-dump:
	@$(MAKE) -C infra migrate-e2e-dump DHIS2_VERSION=$(or $(DHIS2_VERSION),v43)

dhis2-versions-check:
	@$(UV) run python infra/scripts/check_version_bumps.py

dhis2-versions-bump:
	@$(UV) run python infra/scripts/check_version_bumps.py --apply

dhis2-codegen-all:
	@infra/scripts/codegen_all_versions.sh $(VERSIONS)

dhis2-codegen-play-v41 dhis2-codegen-play-v42 dhis2-codegen-play-v43:
	@infra/scripts/codegen_play.sh $(@:dhis2-codegen-play-%=%)

dhis2-codegen-play: dhis2-codegen-play-v41 dhis2-codegen-play-v42 dhis2-codegen-play-v43

refresh-analytics:
	@echo ">>> Refreshing analytics tables (blocks until ANALYTICS_TABLE task completes)"
	@if [ -f infra/home/credentials/.env.auth ]; then \
		set -a; . infra/home/credentials/.env.auth; set +a; \
		$(UV) run d2w maintenance refresh analytics --watch --timeout 600; \
	else \
		$(UV) run d2w maintenance refresh analytics --watch --timeout 600; \
	fi

verify-examples:
	@echo ">>> Running every non-interactive example against profile $${DHIS2_PROFILE:-local_basic} (version resolved from the profile)"
	@if [ -f infra/home/credentials/.env.auth ]; then \
		set -a; . infra/home/credentials/.env.auth; set +a; \
		DHIS2_VERSION=$(DHIS2_VERSION) $(UV) run python -u infra/scripts/verify_examples.py; \
	else \
		echo "    note: infra/home/credentials/.env.auth missing — env-dependent examples (profile_crud.py) will fail"; \
		DHIS2_VERSION=$(DHIS2_VERSION) $(UV) run python -u infra/scripts/verify_examples.py; \
	fi

refresh-setup:
	@echo ">>> [1/2] Rebuilding e2e dump (wipes + reseeds the stack)"
	@$(MAKE) dhis2-build-e2e-dump
	@echo ">>> [2/2] Seeding PATs + OAuth2 client (writes .env.auth)"
	@$(MAKE) -C infra seed
	@echo ">>> Setup complete — run 'make verify-examples' to exercise the example suite"

refresh-and-verify:
	@echo ">>> [1/4] Rebuilding e2e dump (wipes + reseeds the stack)"
	@$(MAKE) dhis2-build-e2e-dump
	@echo ">>> [2/4] Seeding PATs + OAuth2 client (writes .env.auth)"
	@$(MAKE) -C infra seed
	@echo ">>> [3/4] Refreshing analytics tables (the analytics examples read them)"
	@$(MAKE) refresh-analytics
	@echo ">>> [4/4] Verifying every non-interactive example (DHIS2 $(or $(DHIS2_VERSION),v43))"
	@set -a; . infra/home/credentials/.env.auth; set +a; \
		DHIS2_VERSION=$(or $(DHIS2_VERSION),v43) $(UV) run python -u infra/scripts/verify_examples.py

clean: clean-artifacts
	@echo ">>> Cleaning"
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .coverage htmlcov coverage.xml
	@rm -rf .pyright
	@rm -rf dist build site

clean-artifacts:
	@echo ">>> Removing run artifacts (reports, screenshots, browser and property-test state)"
	@rm -rf .hypothesis .playwright-mcp
	@find . -maxdepth 1 -type f -name "*.png" -delete
	@echo "    the working tree holds no run output; regenerate any of it by re-running its command"

.DEFAULT_GOAL := help
