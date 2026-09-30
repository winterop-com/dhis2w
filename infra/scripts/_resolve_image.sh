#!/usr/bin/env bash
#
# Resolve the pinned DHIS2 Docker image reference from a minor version key.
#
# When sourced, exports `DHIS2_IMAGE` (alongside the caller's
# pre-existing `DHIS2_VERSION`) so docker compose picks up both.
# When run directly, prints the image to stdout — convenient for Make:
#
#     DHIS2_IMAGE := $(shell scripts/_resolve_image.sh $(DHIS2_VERSION))
#
# Inputs (in priority order):
#   $1                      — version key in vXX form (v43)
#   $DHIS2_VERSION env var  — same, used when no positional arg
#
# A pin in `infra/versions.env` is either a `dhis2/core` tag (`2.43.1.0`,
# printed as `dhis2/core:2.43.1.0`) or a full image reference containing
# `/` (`dhis2/core-dev@sha256:...`, printed as-is) for a major with no
# release yet. A dotted tag passed directly (e.g. "2.43.0.0") bypasses the
# lookup, which runs a specific tag without editing versions.env.
#
# Fails fast if no pin exists for the given minor.
#
# The pin source of truth is `infra/versions.env`. Bumping any pin is an
# explicit action: re-run codegen and commit the regen in the same PR.

set -eu

_input="${1:-${DHIS2_VERSION:-}}"
if [ -z "$_input" ]; then
  echo "_resolve_image.sh: no version provided (positional arg or DHIS2_VERSION env)" >&2
  exit 1
fi

_resolve_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_versions_env="$_resolve_dir/versions.env"

# A full dotted tag is used as-is; a vXX key resolves through versions.env
# (whose keys are digit-suffixed: `DHIS2_V43`). A bare digit is rejected.
case "$_input" in
  *.*)
    _pin="$_input"
    ;;
  v[0-9]*)
    if [ ! -f "$_versions_env" ]; then
      echo "_resolve_image.sh: $_versions_env missing" >&2
      exit 1
    fi
    # shellcheck disable=SC1090
    . "$_versions_env"
    _n="${_input#v}"
    _pin_var="DHIS2_V${_n}"
    if [ -z "${!_pin_var:-}" ]; then
      echo "_resolve_image.sh: no pin for DHIS2_V${_n} in $_versions_env" >&2
      echo "  add 'DHIS2_V${_n}=2.${_n}.0.0' to fix" >&2
      exit 1
    fi
    _pin="${!_pin_var}"
    ;;
  *)
    echo "_resolve_image.sh: invalid DHIS2_VERSION '$_input' — use the vXX form (e.g. v43) or a full dotted tag (e.g. 2.43.0.0)" >&2
    exit 1
    ;;
esac

case "$_pin" in
  */*) _image="$_pin" ;;
  *) _image="dhis2/core:$_pin" ;;
esac

# Sourced: export the resolved image (and the original minor key for compose's
# dump-path lookup). Run directly: print the image and exit cleanly.
if (return 0 2>/dev/null); then
  export DHIS2_VERSION="$_input"
  export DHIS2_IMAGE="$_image"
else
  printf '%s\n' "$_image"
fi
