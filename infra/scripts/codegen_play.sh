#!/usr/bin/env bash
#
# Refresh the /api/schemas half of `generated/v{N}` from the public play
# demo of the pinned release, without docker.
#
# The pin `DHIS2_V43=2.43.2.0` maps to the alias `https://play.dhis2.org/2.43`,
# which redirects to the latest 2.43 release on play. The script refuses to
# run when that release is not the pin: bump the pin first
# (`make dhis2-versions-bump`).
#
# Only `generate` runs here. The OpenAPI document depends on `dhis.conf`
# (play runs without the OAuth2 dynamic client registration this repo's
# stack enables, so `/api/auth/enrollDevice` is missing), so `openapi.json`
# is captured from the local stack by `codegen_all_versions.sh` instead.
#
# Usage:
#   infra/scripts/codegen_play.sh v43

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 vNN" >&2
  exit 2
fi

version_key="$1"
infra_dir="$(cd "$(dirname "$0")/.." && pwd)"
repo_root="$(cd "$infra_dir/.." && pwd)"

image="$("$infra_dir/scripts/_resolve_image.sh" "$version_key")"
case "$image" in
  dhis2/core:2.*) pin="${image#dhis2/core:}" ;;
  *)
    echo "!!! $version_key is pinned to '$image', which has no stable play channel" >&2
    exit 1
    ;;
esac

# 2.43.2.0 -> major.minor.patch 2.43.2 (what play reports) and alias 2.43
release="$(echo "$pin" | cut -d. -f1-3)"
url="https://play.dhis2.org/$(echo "$pin" | cut -d. -f1-2)"

# --location-trusted keeps the credential on the alias's redirect to play.im.dhis2.org.
reported="$(curl -fsSL --location-trusted -u admin:district "$url/api/system/info" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
if [ "$reported" != "$release" ]; then
  echo "!!! $url reports $reported, expected $release" >&2
  exit 1
fi

echo ">>> Refreshing generated/$version_key from $url ($reported)"
cd "$repo_root"
uv run d2w dev codegen generate --url "$url" --username admin --password district --follow-redirects-with-auth
