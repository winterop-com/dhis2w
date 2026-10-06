#!/usr/bin/env bash
#
# Capture the OpenAPI document of one pinned DHIS2 major across several
# fresh boots, then list every JSON pointer whose value differs between them.
#
# DHIS2 builds `/api/openapi/openapi.json` at startup, and on 2.42.6, 2.43.1 and 2.43.2
# the same image yields a different document on each boot (BUGS.md #133):
# where two Java members collide, the one that wins changes. The committed
# `generated/v{N}/openapi.json` is one such draw, so every component this
# script reports is a candidate for the `pin-boot-dependent-shapes` spec patch.
#
# Usage:
#   infra/scripts/openapi_stability.sh v43 <output-dir> [boots]   # default 3 boots
#
# Each boot lands in <output-dir>/boot-<n>/v43/openapi.json; the report is
# printed at the end and written to <output-dir>/flips.json.

set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 vNN <output-dir> [boots]" >&2
  exit 2
fi

version_key="$1"
output_dir="$2"
boots="${3:-3}"

INFRA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"

# shellcheck source=_placeholder_dumps.sh
. "$INFRA_DIR/scripts/_placeholder_dumps.sh"
placeholder_dumps_install

documents=()
for boot in $(seq 1 "$boots"); do
  echo
  echo ">>> DHIS2 $version_key boot $boot of $boots"
  make -C "$INFRA_DIR" up-fresh DHIS2_VERSION="$version_key"
  make -C "$INFRA_DIR" wait
  boot_root="$output_dir/boot-$boot"
  (cd "$REPO_ROOT" && uv run d2w dev codegen fetch-openapi \
      --url http://localhost:8080 --username admin --password district \
      --output-root "$boot_root")
  documents+=("$boot_root/$version_key/openapi.json")
  make -C "$INFRA_DIR" down >/dev/null 2>&1 || true
done

(cd "$REPO_ROOT" && uv run d2w dev codegen oas-flips "${documents[@]}" --json) > "$output_dir/flips.json"
(cd "$REPO_ROOT" && uv run d2w dev codegen oas-flips "${documents[@]}")
