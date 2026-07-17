"""Generate or verify the lockfile-backed dependency license inventory."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import tomllib
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "DEPENDENCY_LICENSES.md"
MAX_INLINE_LICENSE_LENGTH = 120


def _python_license(name: str) -> str:
    metadata = importlib.metadata.metadata(name)
    expression = metadata.get("License-Expression")
    if expression:
        return expression.strip()
    classifiers = [
        value.removeprefix("License :: ")
        for value in metadata.get_all("Classifier", [])
        if value.startswith("License :: ")
    ]
    if classifiers:
        return "; ".join(classifiers)
    value = (metadata.get("License") or "REVIEW REQUIRED").strip().splitlines()[0]
    return value if len(value) <= MAX_INLINE_LICENSE_LENGTH else "SEE PACKAGE METADATA"


def _python_rows() -> list[tuple[str, str, str]]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    rows: list[tuple[str, str, str]] = []
    dependencies = [
        *project["project"]["dependencies"],
        *project["dependency-groups"]["dev"],
    ]
    for requirement in dependencies:
        name_part, version = requirement.split("==", 1)
        name = name_part.split("[", 1)[0]
        rows.append((name, version, _python_license(name)))
    return sorted(rows)


def _node_rows() -> list[tuple[str, str, str]]:
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    rows: list[tuple[str, str, str]] = []
    for path, package in lock["packages"].items():
        if "node_modules/" not in path or "version" not in package:
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        rows.append((name, package["version"], package.get("license", "REVIEW REQUIRED")))
    return sorted(rows)


def _table(rows: list[tuple[str, str, str]]) -> str:
    lines = ["| Package | Version | Declared license |", "| --- | --- | --- |"]
    lines.extend(
        f"| `{name}` | `{version}` | {license_name} |"
        for name, version, license_name in rows
    )
    return "\n".join(lines)


def render() -> str:
    """Render the installed-metadata and lockfile inventory deterministically."""
    python_rows = _python_rows()
    node_rows = _node_rows()
    return (
        "# Dependency license inventory\n\n"
        "Generated from exact direct Python requirements, installed Python package "
        "metadata, and the complete `frontend/package-lock.json` npm graph. Locked "
        "Python transitive versions remain in `uv.lock`. This is an inventory, not legal advice; "
        "package license files remain authoritative. Regenerate with "
        "`uv run python scripts/generate_dependency_licenses.py`.\n\n"
        f"Direct Python packages: {len(python_rows)}. Locked npm packages: {len(node_rows)}.\n\n"
        "## Direct Python requirements\n\n"
        f"{_table(python_rows)}\n\n"
        "## npm lock\n\n"
        f"{_table(node_rows)}\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Write the inventory, or fail when the checked-in copy has drifted."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    rendered = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print("dependency license inventory is out of date")
            return 1
        print("dependency license inventory matches lockfiles")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
