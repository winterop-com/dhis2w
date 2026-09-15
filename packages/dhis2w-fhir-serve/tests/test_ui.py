"""`--ui`: the built bundle is served alongside the FHIR routes, and shadows none of them.

The whole risk of mounting static files on this app is ordering, and it cuts both ways. A mount
registered one line too early answers `/metadata` with `index.html` and every Bundle read with the
SPA shell. A mount registered entirely too late never serves `/assets/index-<hash>.js` at all,
because `/{resource_type}/{resource_id}` claims two-segment paths and answers that one with an
OperationOutcome saying `assets` is not a served resource type - a white page whose console says
404 and whose cause is in the router table. So the assets mount goes before the catch-alls and the
shell mount goes after, and both halves are held here.

The bundle is a build artifact, gitignored and produced by `make ui`, so these tests
write a minimal stand-in rather than requiring node to be installed to run pytest. The one test
that reads the real bundle skips when it has not been built.

The build stamp is the other half. A checkout serves whatever `make ui` last wrote, which is how a
merged and tested frontend change reaches nobody: the TypeScript is current, vitest is green, and
the JavaScript in the browser is last week's. So the stamp names the source a build read and a
checkout grades its bundle against the source beside it - and the tests for that build both shapes
in a temporary directory, a checkout (a `frontend/src` beside the bundle) and a wheel (none).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx2
import pytest
from dhis2w_fhir.config import FhirProject
from dhis2w_fhir_serve import ui as ui_module
from dhis2w_fhir_serve.app import create_app
from dhis2w_fhir_serve.settings import ServeSettings
from dhis2w_fhir_serve.ui import (
    CaptureUiBuildStamp,
    UiBundleMissingError,
    UiBundleStaleError,
    fingerprint_frontend_source,
    frontend_source_directory,
    mount_ui_assets,
    read_ui_build_stamp,
    ui_bundle_present,
    write_build_stamp,
)
from fastapi import FastAPI

#: The service base the in-process client uses, matching the one every other serve test uses.
BASE_URL = "http://serve.test"

#: What the stand-in bundle's shell says, so a test can tell it from a FHIR answer at a glance.
INDEX_MARKUP = '<!doctype html>\n<html lang="en"><body><div id="root"></div></body></html>\n'

#: One hashed asset, so the immutable cache policy has something to apply to.
ASSET_SOURCE = 'console.log("capture ui")\n'


@pytest.fixture
def built_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A minimal built bundle at the path the mount reads, pointed there for the test only."""
    static_directory = tmp_path / "static"
    (static_directory / "assets").mkdir(parents=True)
    (static_directory / "index.html").write_text(INDEX_MARKUP, encoding="utf-8")
    (static_directory / "assets" / "index-abc123.js").write_text(ASSET_SOURCE, encoding="utf-8")
    monkeypatch.setattr(ui_module, "STATIC_DIRECTORY", static_directory)
    yield static_directory


@pytest.fixture
def missing_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A static directory with nothing built in it, as a fresh checkout has."""
    static_directory = tmp_path / "static"
    static_directory.mkdir()
    monkeypatch.setattr(ui_module, "STATIC_DIRECTORY", static_directory)
    yield static_directory


@pytest.fixture
def ui_app(compiled_project: FhirProject, built_bundle: Path) -> FastAPI:
    """The facade over the compiled project, with the capture UI mounted."""
    _ = built_bundle
    return create_app(ServeSettings(project_dir=compiled_project.project_root, ui=True))


@pytest.fixture
async def ui_client(ui_app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    """An in-process client over the facade with the UI mounted, lifespan run around the test."""
    async with ui_app.router.lifespan_context(ui_app):
        transport = httpx2.ASGITransport(app=ui_app)
        async with httpx2.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            yield http


async def test_root_serves_the_shell(ui_client: httpx2.AsyncClient) -> None:
    """`/` answers the built index.html, which is what makes the UI reachable at all."""
    response = await ui_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="root"' in response.text


async def test_the_shell_takes_the_read_and_leaves_the_batch_refusal_alone(ui_client: httpx2.AsyncClient) -> None:
    """A mount at `/` answers GET and would answer POST with a bare 405, so the FHIR refusal mounts ahead of it."""
    response = await ui_client.post("/", json={"resourceType": "Bundle", "type": "batch"})

    assert response.status_code == 405
    assert response.headers["content-type"] == "application/fhir+json"
    assert "no batch and no transaction" in response.json()["issue"][0]["diagnostics"]


async def test_metadata_still_wins(ui_client: httpx2.AsyncClient) -> None:
    """The conformance endpoint answers FHIR, not the shell - the mount is registered after it."""
    response = await ui_client.get("/metadata")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/fhir+json")
    assert response.json()["resourceType"] == "CapabilityStatement"


@pytest.mark.parametrize(
    "path",
    [
        "/Questionnaire",
        "/Questionnaire/d2-pr-anc-visit-q",
        "/QuestionnaireResponse",
        "/CodeSystem",
        "/Organization",
        "/StructureDefinition",
    ],
)
async def test_fhir_reads_still_win(ui_client: httpx2.AsyncClient, path: str) -> None:
    """Every read the facade answers is still answered as FHIR with the UI mounted.

    The paths are the types this project publishes, which is the set its `/metadata` declares: a type
    it publishes none of is a type it declares no interaction for, and the read catch-all answers 404
    for it whether or not the UI is mounted.
    """
    response = await ui_client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/fhir+json")


async def test_an_unserved_type_is_still_refused_as_fhir(ui_client: httpx2.AsyncClient) -> None:
    """A resource type the facade does not serve is an OperationOutcome, not the SPA shell.

    This is the case the mount would quietly swallow if it were registered before the read
    catch-alls: `/Patient` matches nothing above the mount and would come back 200 text/html.
    """
    response = await ui_client.get("/Patient")
    assert response.status_code == 404
    assert response.json()["resourceType"] == "OperationOutcome"


async def test_a_capture_still_posts(ui_client: httpx2.AsyncClient) -> None:
    """The capture route answers a POST, so the mount did not claim the write path either."""
    response = await ui_client.post(
        "/QuestionnaireResponse",
        content=json.dumps({"resourceType": "QuestionnaireResponse", "status": "completed"}),
        headers={"Content-Type": "application/fhir+json"},
    )
    # The body is deliberately not a valid capture: what is under test is that the capture route
    # is the one that answered, which its OperationOutcome refusal proves as well as a 201 would.
    assert response.json()["resourceType"] == "OperationOutcome"


async def test_the_shell_revalidates_and_assets_do_not(ui_client: httpx2.AsyncClient) -> None:
    """A hashed asset is immutable; the shell that names the hashes must never be cached."""
    shell = await ui_client.get("/")
    assert shell.headers["cache-control"] == "no-cache"
    asset = await ui_client.get("/assets/index-abc123.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_a_missing_bundle_is_one_line(missing_bundle: Path, compiled_project: FhirProject) -> None:
    """`--ui` with nothing built refuses at app build time, naming the command that fixes it."""
    _ = missing_bundle
    with pytest.raises(UiBundleMissingError) as raised:
        create_app(ServeSettings(project_dir=compiled_project.project_root, ui=True))
    message = str(raised.value)
    assert "make ui" in message
    assert "\n" not in message


def test_a_missing_bundle_is_a_lookup_error(missing_bundle: Path) -> None:
    """The refusal is a LookupError, which is the shape the CLI error funnel renders as one line."""
    _ = missing_bundle
    assert issubclass(UiBundleMissingError, LookupError)
    with pytest.raises(LookupError):
        mount_ui_assets(FastAPI())


def test_bundle_presence_reads_the_shell_not_the_directory(missing_bundle: Path) -> None:
    """An empty static directory is not a built bundle - the index file is what counts."""
    assert ui_bundle_present() is False
    (missing_bundle / "index.html").write_text(INDEX_MARKUP, encoding="utf-8")
    assert ui_bundle_present() is True


@pytest.mark.skipif(not ui_bundle_present(), reason="no built frontend; run `make ui`")
async def test_the_real_bundle_serves_every_asset_its_shell_names(compiled_project: FhirProject) -> None:
    """Against a real `make ui` output, every script and stylesheet the shell names loads.

    The stand-in bundle above proves the two mounts are ordered correctly; this one proves the
    vite build actually emits what those mounts expect - everything under `assets/`, referenced by
    absolute path. A root-level emitted file would be a one-segment path, the search catch-all
    would claim it, and this test is what says so.
    """
    application = create_app(ServeSettings(project_dir=compiled_project.project_root, ui=True))
    async with application.router.lifespan_context(application):
        transport = httpx2.ASGITransport(app=application)
        async with httpx2.AsyncClient(transport=transport, base_url=BASE_URL) as http:
            shell = await http.get("/")
            assert shell.status_code == 200
            referenced = re.findall(r'(?:src|href)="(/[^"]+)"', shell.text)
            assert referenced, "the built shell references no assets at all"
            for reference in referenced:
                asset = await http.get(reference)
                assert asset.status_code == 200, f"{reference} did not load"


async def test_the_facade_mounts_nothing_by_default(client: httpx2.AsyncClient) -> None:
    """Without `--ui` the root is not served at all, so a plain endpoint stays a plain endpoint."""
    response = await client.get("/")
    assert response.status_code == 404


@pytest.fixture
def bundle_in_a_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A built bundle with a frontend checkout beside it, laid out the way the package is on disk.

    The bundle sits at `<package>/src/dhis2w_fhir_serve/static` and the sources it was built from at
    `<package>/frontend`, which is the relationship `frontend_source_directory` walks. The stamp is
    deliberately not written here: each test says for itself whether this bundle was ever stamped.
    """
    package_directory = tmp_path / "dhis2w-fhir-serve"
    static_directory = package_directory / "src" / "dhis2w_fhir_serve" / "static"
    (static_directory / "assets").mkdir(parents=True)
    (static_directory / "index.html").write_text(INDEX_MARKUP, encoding="utf-8")
    (static_directory / "assets" / "index-abc123.js").write_text(ASSET_SOURCE, encoding="utf-8")
    frontend_directory = package_directory / "frontend"
    (frontend_directory / "src" / "lib").mkdir(parents=True)
    (frontend_directory / "src" / "main.tsx").write_text("export const shell = 1\n", encoding="utf-8")
    (frontend_directory / "src" / "lib" / "orgunits.ts").write_text("export const units = []\n", encoding="utf-8")
    (frontend_directory / "package.json").write_text('{"name": "capture-ui"}\n', encoding="utf-8")
    monkeypatch.setattr(ui_module, "STATIC_DIRECTORY", static_directory)
    yield package_directory


def test_a_wheel_has_no_frontend_source_to_grade_against(built_bundle: Path) -> None:
    """An installed bundle stands alone, so nothing compares it with sources that are not there."""
    _ = built_bundle
    assert frontend_source_directory() is None


def test_a_checkout_finds_the_frontend_beside_the_bundle(bundle_in_a_checkout: Path) -> None:
    """The sources a build reads are found from the bundle alone - no configuration says where they are."""
    assert frontend_source_directory() == bundle_in_a_checkout / "frontend"


def test_a_stamp_names_the_source_the_build_read(bundle_in_a_checkout: Path) -> None:
    """`make ui` closes by writing what it read, and the bundle answers with it."""
    written = write_build_stamp()
    read_back = read_ui_build_stamp()

    assert read_back == written
    assert written.fingerprint == fingerprint_frontend_source(bundle_in_a_checkout / "frontend")


def test_one_source_edit_moves_the_fingerprint(bundle_in_a_checkout: Path) -> None:
    """The fingerprint covers file content, so a one-line change to any source is a different build."""
    frontend_directory = bundle_in_a_checkout / "frontend"
    before = fingerprint_frontend_source(frontend_directory)
    (frontend_directory / "src" / "lib" / "orgunits.ts").write_text("export const units = [1]\n", encoding="utf-8")

    assert fingerprint_frontend_source(frontend_directory) != before


def test_the_fingerprint_is_the_same_twice_over_one_checkout(bundle_in_a_checkout: Path) -> None:
    """Two readings of one unchanged checkout agree, or every run would refuse its own bundle."""
    frontend_directory = bundle_in_a_checkout / "frontend"

    assert fingerprint_frontend_source(frontend_directory) == fingerprint_frontend_source(frontend_directory)


def test_a_current_bundle_serves(bundle_in_a_checkout: Path, compiled_project: FhirProject) -> None:
    """A bundle stamped with the source in front of it is what `--ui` is for, and it mounts."""
    _ = bundle_in_a_checkout
    write_build_stamp()

    assert create_app(ServeSettings(project_dir=compiled_project.project_root, ui=True)) is not None


def test_a_bundle_older_than_the_source_is_refused(bundle_in_a_checkout: Path, compiled_project: FhirProject) -> None:
    """The failure this guard exists for: current TypeScript, last week's JavaScript, and no sign of it."""
    stamp = write_build_stamp()
    (bundle_in_a_checkout / "frontend" / "src" / "lib" / "orgunits.ts").write_text(
        "export const units = [1]\n", encoding="utf-8"
    )

    with pytest.raises(UiBundleStaleError) as raised:
        create_app(ServeSettings(project_dir=compiled_project.project_root, ui=True))

    message = str(raised.value)
    assert "make ui" in message
    assert stamp.fingerprint[:12] in message
    assert "\n" not in message


def test_an_unstamped_bundle_in_a_checkout_is_refused(
    bundle_in_a_checkout: Path, compiled_project: FhirProject
) -> None:
    """A bundle built before it was stamped is a bundle nothing can date, which is the same refusal."""
    _ = bundle_in_a_checkout

    with pytest.raises(UiBundleStaleError) as raised:
        create_app(ServeSettings(project_dir=compiled_project.project_root, ui=True))

    assert "carries no build stamp" in str(raised.value)


def test_a_wheel_is_never_refused_for_staleness(built_bundle: Path, compiled_project: FhirProject) -> None:
    """An installed wheel carries the bundle CI built and no source to grade it against, so it serves."""
    _ = built_bundle

    assert create_app(ServeSettings(project_dir=compiled_project.project_root, ui=True)) is not None


def test_the_stamp_describes_itself_in_one_line() -> None:
    """The serve banner prints this, so it names the build date and the source in one readable line."""
    stamp = CaptureUiBuildStamp.model_validate(
        {"fingerprint": "0123456789abcdef" * 4, "built_at": "2026-09-15T01:15:00Z"}
    )

    described = stamp.describe()

    assert described == "capture UI bundle built 2026-09-15 01:15 UTC from frontend source 0123456789ab"
