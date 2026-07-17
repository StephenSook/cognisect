"""Fail closed when tracked public-repository boundaries or pins drift."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATH_PARTS = {
    ".superpowers",
    "private",
    "reference-materials",
    "reference-captures",
    "restricted",
    "raw",
    "superpowers",
}
FORBIDDEN_SUFFIXES = {".key", ".pem", ".pdf", ".sqlite", ".sqlite3"}
FORBIDDEN_TRACKED_PATHS = {
    "PLAN.md",
    "docs/BUILD_LOG.md",
    "docs/EDUCATOR_REVIEW.md",
    "docs/FACT_SHEET.md",
    "docs/SUBMISSION_COPY.md",
}
SECRET_PATTERNS = {
    "OpenAI-like key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "credentialed public database URL": re.compile(
        r"postgres(?:ql)?://[^\s:/]+:[^\s@]+@(?!(?:localhost|127\.0\.0\.1|db)(?::|/))"
    ),
}
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _tracked_files() -> tuple[Path, ...]:
    git = shutil.which("git")
    if git is None:
        msg = "git executable is required"
        raise RuntimeError(msg)
    completed = subprocess.run(
        [git, "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(
        ROOT / raw.decode("utf-8")
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def _check_paths(paths: tuple[Path, ...]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT)
        if relative.as_posix() in FORBIDDEN_TRACKED_PATHS:
            errors.append(f"forbidden internal process artifact: {relative}")
        if any(part.lower() in FORBIDDEN_PATH_PARTS for part in relative.parts):
            errors.append(f"forbidden tracked path: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden tracked suffix: {relative}")
    return errors


def _check_secrets(paths: tuple[Path, ...]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{label} matched in {path.relative_to(ROOT)}")
    return errors


def _check_dependency_pins() -> list[str]:
    errors: list[str] = []
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    python_dependencies = [
        *pyproject["project"]["dependencies"],
        *pyproject["dependency-groups"]["dev"],
    ]
    errors.extend(
        f"Python dependency is not exact: {dependency}"
        for dependency in python_dependencies
        if "==" not in dependency
    )

    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    for group in ("dependencies", "devDependencies"):
        for name, version in package[group].items():
            if not EXACT_VERSION.fullmatch(version):
                errors.append(f"npm dependency is not exact: {name}@{version}")
    return errors


def main() -> int:
    """Run the public-boundary, credential, license, and pin checks."""
    paths = _tracked_files()
    errors = [*_check_paths(paths), *_check_secrets(paths), *_check_dependency_pins()]
    errors.extend(
        f"required public file is not tracked: {required}"
        for required in (
            "LICENSE",
            "NOTICE",
            "THIRD_PARTY_NOTICES.md",
            "docs/DEPENDENCY_LICENSES.md",
        )
        if ROOT / required not in paths
    )
    if errors:
        print("public repository check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"public repository check passed for {len(paths)} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
