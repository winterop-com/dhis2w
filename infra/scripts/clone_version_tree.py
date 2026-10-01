"""Copy the hand-written `v{N}` trees of dhis2w-client and dhis2w-core to a new DHIS2 major.

The copy rewrites version tokens (`dhis2w_client.v43`, `home="v43"`, `Dhis2.V43`) and turns
`v43-only` into `v43+`, since the new major inherits the source's features. Release strings
such as `2.43.1` stay: they record what was observed on that release. Every line that still
mentions the source major, or names the new major beside another version key, is listed at the end
for a reviewer.

Usage:
    uv run python infra/scripts/clone_version_tree.py v43 v44
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TREE_PARENTS = (
    _REPOSITORY_ROOT / "packages" / "dhis2w-client" / "src" / "dhis2w_client",
    _REPOSITORY_ROOT / "packages" / "dhis2w-core" / "src" / "dhis2w_core",
)
_VERSION_KEY_RE = re.compile(r"^v(\d+)$")
# Hand-written modules that live inside the generated tree; codegen never emits them.
_GENERATED_ROOT = _REPOSITORY_ROOT / "packages" / "dhis2w-client" / "src" / "dhis2w_client" / "generated"
_GENERATED_HAND_WRITTEN = ("tracker.py",)

app = typer.Typer(help="Clone a hand-written version tree to a new DHIS2 major.", add_completion=False)


class LeftoverLine(BaseModel):
    """A line in the new tree that still names the source major."""

    model_config = ConfigDict(frozen=True)

    path: Path
    line_number: int
    text: str


def _major(version_key: str) -> str:
    """Return the digits of a `vNN` key, or fail with a usage error."""
    match = _VERSION_KEY_RE.match(version_key)
    if match is None:
        raise typer.BadParameter(f"expected a key like v43, got {version_key!r}")
    return match.group(1)


def _rewrite(text: str, source: str, target: str) -> str:
    """Rewrite the source major's version tokens to the target major."""
    text = re.sub(rf"\bv{source}-only\b", f"v{source}+", text)
    text = re.sub(rf"\bv{source}\b(?!\+)", f"v{target}", text)
    return re.sub(rf"\bV{source}\b", f"V{target}", text)


def _leftovers(tree: Path, source: str, target: str) -> list[LeftoverLine]:
    """List lines in `tree` a reviewer should read after the rewrite.

    That is every line still naming the source major, and every line naming the new major next to
    another version key: an enumeration such as `v41 / v42 / v43` rewrites to `v41 / v42 / v44`.
    """
    source_pattern = re.compile(rf"\b(v{source}\+|2\.{source}\b|{source}\b)")
    other_key_pattern = re.compile(rf"\bv(?!{target}\b)\d+\b")
    found: list[LeftoverLine] = []
    for path in sorted(tree.rglob("*.py")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            mentions_target = re.search(rf"\bv{target}\b", line) is not None
            if source_pattern.search(line) or (mentions_target and other_key_pattern.search(line)):
                found.append(LeftoverLine(path=path, line_number=line_number, text=line.strip()))
    return found


@app.command()
def clone(
    source_key: Annotated[str, typer.Argument(help="Tree to copy, e.g. v43.")],
    target_key: Annotated[str, typer.Argument(help="New tree, e.g. v44.")],
) -> None:
    """Copy both hand-written trees from `source_key` to `target_key` and rewrite version tokens."""
    source = _major(source_key)
    target = _major(target_key)
    for parent in _TREE_PARENTS:
        source_tree = parent / source_key
        target_tree = parent / target_key
        if not source_tree.is_dir():
            raise typer.BadParameter(f"no tree at {source_tree}")
        if target_tree.exists():
            raise typer.BadParameter(f"{target_tree} already exists; remove it first")
        shutil.copytree(source_tree, target_tree, ignore=shutil.ignore_patterns("__pycache__"))
        for path in sorted(target_tree.rglob("*.py")):
            original = path.read_text(encoding="utf-8")
            rewritten = _rewrite(original, source, target)
            if rewritten != original:
                path.write_text(rewritten, encoding="utf-8")
        typer.echo(f"cloned {source_tree.relative_to(_REPOSITORY_ROOT)} -> {target_tree.relative_to(_REPOSITORY_ROOT)}")
        for leftover in _leftovers(target_tree, source, target):
            relative = leftover.path.relative_to(_REPOSITORY_ROOT)
            typer.echo(f"  review {relative}:{leftover.line_number}: {leftover.text}")
    for name in _GENERATED_HAND_WRITTEN:
        source_file = _GENERATED_ROOT / source_key / name
        target_file = _GENERATED_ROOT / target_key / name
        if not source_file.exists():
            continue
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(_rewrite(source_file.read_text(encoding="utf-8"), source, target), encoding="utf-8")
        typer.echo(f"cloned {source_file.relative_to(_REPOSITORY_ROOT)} -> {target_file.relative_to(_REPOSITORY_ROOT)}")


if __name__ == "__main__":
    app()
