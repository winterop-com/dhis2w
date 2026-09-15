"""The capture UI: a built React bundle, served same-origin off the facade itself.

THE BUNDLE MOUNTS IN TWO PIECES, AND THE ORDER OF THE TWO IS THE WHOLE DESIGN.

Starlette matches routes in registration order, and the facade's read routes are catch-alls:
`/{resource_type}` claims every one-segment path and `/{resource_type}/{resource_id}` claims every
two-segment one. So a naive single mount at `/` placed last serves the shell and nothing else -
`/assets/index-<hash>.js` is a two-segment path, the read route claims it first, and the browser
gets a FHIR OperationOutcome saying `assets` is not a resource type this server serves. The page
loads white with a 404 in the console and nothing anywhere says why.

Hence:

- `mount_ui_assets` registers `/assets` BEFORE the read catch-alls. It is a fixed path, exactly
  like `/metadata` and `/ConceptMap/$translate`, and belongs with them.
- `mount_ui_shell` registers `/` AFTER everything, because it matches whatever is left.

That is also why the vite build must keep every emitted file under `assets/`: a root-level file
would be a one-segment path and the search catch-all would claim it. There is no `public/`
directory in the frontend for exactly this reason.

A missing bundle is a refusal rather than a blank page. `--ui` on a checkout that has never run
`make ui` has no `index.html` to serve, and mounting an empty directory would answer
404 for the shell and 200 for nothing. So the mount raises while the app is being built, naming
the command that fixes it.

A STALE BUNDLE IS THE SAME REFUSAL, AND IT IS THE ONE THAT ACTUALLY BITES.

The bundle is a build artifact: gitignored, written by `make ui`, and never carried by a pull. A
checkout whose TypeScript gained a fix an hour ago still serves the JavaScript it built last week,
the browser shows the old behaviour, vitest passes on the source nobody is running, and no line
anywhere says the two have parted. So `make ui` writes `static/build.json` naming the frontend
source it read - `fingerprint_frontend_source` over `src/` and the root files vite reads - and a
checkout compares that stamp against the source in front of it before mounting anything. A
mismatch, or a bundle carrying no stamp at all, refuses the run and names `make ui`.

Only a checkout compares. An installed wheel carries the bundle CI built and no `frontend/` beside
it, so `frontend_source_directory` answers None there and the stamp is printed rather than graded.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

#: Where the built bundle lives inside the installed package - the vite `build.outDir`.
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"

#: The file whose presence means a bundle was actually built, rather than the directory existing.
INDEX_FILENAME = "index.html"

#: What `make ui` writes beside the shell, naming the frontend source that build read.
BUILD_STAMP_FILENAME = "build.json"

#: The frontend checkout, found from the bundle: `<package>/src/dhis2w_fhir_serve/static` -> `<package>/frontend`.
FRONTEND_DIRECTORY_NAME = "frontend"

#: The directory of frontend sources vite compiles, under the frontend checkout.
FRONTEND_SOURCE_DIRECTORY_NAME = "src"

#: The files beside `src/` that a vite build also reads, so a change to one of them is a change to the bundle.
FRONTEND_ROOT_SOURCES = ("package.json", "index.html", "vite.config.ts")

#: Where vite emits every hashed asset, and the path they are served from.
ASSETS_DIRECTORY_NAME = "assets"
ASSETS_MOUNT_PATH = f"/{ASSETS_DIRECTORY_NAME}"

#: The mount names, so either route can be found by name in a test or a debug dump.
UI_ASSETS_MOUNT_NAME = "ui-assets"
UI_SHELL_MOUNT_NAME = "ui"


class CaptureUiBuildStamp(BaseModel):
    """What one `make ui` produced: the frontend source it read, and when it read it."""

    model_config = ConfigDict(frozen=True)

    fingerprint: str
    built_at: datetime

    def describe(self) -> str:
        """The one line the serve banner prints: when the bundle was built, and from which source."""
        return (
            f"capture UI bundle built {self.built_at:%Y-%m-%d %H:%M} UTC from frontend source {self.fingerprint[:12]}"
        )


class UiBundleMissingError(LookupError):
    """No built UI to serve, rendered by the CLI error funnel as one line naming the fix."""

    def __init__(self) -> None:
        """Carry the refusal naming the directory that is empty and the command that fills it."""
        super().__init__(
            f"`--ui` needs a built frontend at {STATIC_DIRECTORY}, and there is none. "
            "Build it with `make ui` (an installed wheel ships it already)."
        )


class UiBundleStaleError(LookupError):
    """The built bundle is older than the frontend source beside it, rendered by the CLI funnel as one line."""

    def __init__(self, *, built_from: str | None, source_now: str) -> None:
        """Carry the refusal naming both fingerprints, so a reader can tell a rebuild from a coincidence."""
        built = f"it was built from {built_from[:12]}" if built_from else "it carries no build stamp"
        super().__init__(
            f"the capture UI bundle at {STATIC_DIRECTORY} is older than the frontend source - "
            f"{built} and the source now reads {source_now[:12]}. Run `make ui` to rebuild it."
        )


class UiStaticFiles(StaticFiles):
    """Static files with a cache policy stated rather than inferred.

    Vite emits content-hashed asset names, so an asset is immutable: its name changes whenever its
    bytes do. `index.html` names the current hashes and must therefore never be cached - a stale
    shell references filenames a rebuild deleted, and the page renders blank. Starlette sends only
    ETag and Last-Modified, and RFC 9111 lets a browser apply heuristic freshness in the absence of
    Cache-Control, so the policy is written down here instead of left to the client's guess.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Answer one static file, marking the shell revalidate-always and every asset immutable."""
        response = await super().get_response(path, scope)
        media_type: Any = getattr(response, "media_type", None)
        if isinstance(media_type, str) and media_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def ui_bundle_present() -> bool:
    """Whether a built bundle is installed beside this module."""
    return (STATIC_DIRECTORY / INDEX_FILENAME).is_file()


def frontend_source_directory() -> Path | None:
    """The frontend checkout beside the bundle, or None where there is none - which is every wheel."""
    candidate = STATIC_DIRECTORY.parents[2] / FRONTEND_DIRECTORY_NAME
    return candidate if (candidate / FRONTEND_SOURCE_DIRECTORY_NAME).is_dir() else None


def fingerprint_frontend_source(frontend_directory: Path) -> str:
    """The sha256 of everything a vite build reads: every file under `src/`, plus the root sources, path and bytes."""
    digest = hashlib.sha256()
    for path in _frontend_source_files(frontend_directory):
        digest.update(path.relative_to(frontend_directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_ui_build_stamp() -> CaptureUiBuildStamp | None:
    """The stamp `make ui` left in the bundle, or None where the bundle carries none."""
    stamp_path = STATIC_DIRECTORY / BUILD_STAMP_FILENAME
    try:
        return CaptureUiBuildStamp.model_validate_json(stamp_path.read_bytes())
    except (OSError, ValueError):
        return None


def write_build_stamp() -> CaptureUiBuildStamp:
    """Stamp the built bundle with the frontend source it came from - the closing step of `make ui`."""
    frontend_directory = frontend_source_directory()
    if frontend_directory is None:
        raise FileNotFoundError(
            f"no frontend checkout beside {STATIC_DIRECTORY}, so there is no source to stamp a build against"
        )
    stamp = CaptureUiBuildStamp(
        fingerprint=fingerprint_frontend_source(frontend_directory),
        built_at=datetime.now(tz=UTC),
    )
    (STATIC_DIRECTORY / BUILD_STAMP_FILENAME).write_text(
        json.dumps(stamp.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    return stamp


def mount_ui_assets(app: FastAPI) -> None:
    """Mount the hashed asset tree at `/assets`, ahead of the read catch-alls.

    Registered with the fixed-path routers rather than after them: `/assets/<file>` is a
    two-segment path, and `/{resource_type}/{resource_id}` would claim it first.
    """
    _require_bundle()
    app.mount(
        ASSETS_MOUNT_PATH,
        UiStaticFiles(directory=STATIC_DIRECTORY / ASSETS_DIRECTORY_NAME),
        name=UI_ASSETS_MOUNT_NAME,
    )


def mount_ui_shell(app: FastAPI) -> None:
    """Mount the shell at `/`, after every FHIR route, so it claims only what is left.

    `html=True` serves `index.html` for `/`. It is also the 404 fallback under this mount, which
    is harmless here precisely because the UI is hash-routed: the browser never asks the server
    for `/responses`, so the fallback is not being used to fake a client-side route table.
    """
    _require_bundle()
    app.mount("/", UiStaticFiles(directory=STATIC_DIRECTORY, html=True), name=UI_SHELL_MOUNT_NAME)


def _require_bundle() -> None:
    """Refuse to mount anything when no bundle was ever built, or when a checkout's has gone stale."""
    if not ui_bundle_present():
        raise UiBundleMissingError
    frontend_directory = frontend_source_directory()
    if frontend_directory is None:
        return
    source_now = fingerprint_frontend_source(frontend_directory)
    stamp = read_ui_build_stamp()
    if stamp is None or stamp.fingerprint != source_now:
        raise UiBundleStaleError(built_from=stamp.fingerprint if stamp else None, source_now=source_now)


def _frontend_source_files(frontend_directory: Path) -> list[Path]:
    """Every file a vite build reads, in one stable order, so two runs over one checkout fingerprint alike."""
    sources = sorted(
        path for path in (frontend_directory / FRONTEND_SOURCE_DIRECTORY_NAME).rglob("*") if path.is_file()
    )
    roots = [frontend_directory / name for name in FRONTEND_ROOT_SOURCES]
    return sources + [path for path in roots if path.is_file()]
