import base64
import binascii
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]

SPEC = importlib.util.spec_from_file_location(
    "generate_dependency_licenses",
    ROOT / "scripts" / "generate_dependency_licenses.py",
)
assert SPEC is not None and SPEC.loader is not None
generate_dependency_licenses = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_dependency_licenses)

VALID_SHA512_SRI = "sha512-" + base64.b64encode(bytes(64)).decode("ascii")


def _assert_registry_artifact(package_path: str, package: dict[str, object]) -> None:
    resolved = package.get("resolved")
    integrity = package.get("integrity")

    assert isinstance(resolved, str) and resolved, f"{package_path} lacks resolved"
    parsed = urlsplit(resolved)
    assert parsed.scheme == "https", f"{package_path} resolved URL must use HTTPS"
    assert parsed.netloc == "registry.npmjs.org", (
        f"{package_path} resolved URL must use registry.npmjs.org without credentials or port"
    )
    assert parsed.username is None and parsed.password is None, (
        f"{package_path} resolved URL must not contain credentials"
    )
    assert not parsed.query and not parsed.fragment, (
        f"{package_path} resolved URL must not contain query or fragment"
    )
    assert parsed.path.startswith("/") and parsed.path.endswith(".tgz"), (
        f"{package_path} resolved URL must identify a tarball"
    )

    assert isinstance(integrity, str) and integrity.startswith("sha512-"), (
        f"{package_path} integrity must use SHA-512 SRI"
    )
    encoded_digest = integrity.removeprefix("sha512-")
    try:
        digest = base64.b64decode(encoded_digest, validate=True)
    except (binascii.Error, ValueError) as exc:
        message = f"{package_path} integrity must contain strict base64"
        raise AssertionError(message) from exc
    assert base64.b64encode(digest).decode("ascii") == encoded_digest, (
        f"{package_path} integrity must use canonical base64"
    )
    assert len(digest) == 64, f"{package_path} integrity must contain a 64-byte SHA-512 digest"


def _ci_job_blocks(source: str) -> list[str]:
    jobs_heading = re.search(r"(?m)^jobs\s*:\s*$", source)
    assert jobs_heading is not None, "CI workflow lacks a jobs mapping"
    jobs_source = source[jobs_heading.end() :]
    starts = list(re.finditer(r"(?m)^  [a-zA-Z0-9_-]+:\s*$", jobs_source))
    return [
        jobs_source[match.start() : starts[index + 1].start() if index + 1 < len(starts) else None]
        for index, match in enumerate(starts)
    ]


def test_node_license_inventory_includes_isolated_openapi_tooling() -> None:
    rows = generate_dependency_licenses._node_rows()

    assert ("openapi-typescript", "7.13.0", "MIT") in rows
    assert ("typescript", "5.9.3", "Apache-2.0") in rows


def test_npm_lock_registry_artifacts_have_url_and_integrity() -> None:
    lock_paths = (
        ROOT / "frontend" / "package-lock.json",
        ROOT / "frontend" / "tools" / "openapi-generator" / "package-lock.json",
    )

    for lock_path in lock_paths:
        packages = json.loads(lock_path.read_text(encoding="utf-8"))["packages"]
        for package_path, package in packages.items():
            if "node_modules/" not in package_path or package.get("link") is True:
                continue
            _assert_registry_artifact(f"{lock_path}: {package_path}", package)


@pytest.mark.parametrize(
    ("resolved", "integrity"),
    [
        ("file:artifact.tgz", VALID_SHA512_SRI),
        ("http://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz", VALID_SHA512_SRI),
        ("https://example.com/pkg/-/pkg-1.0.0.tgz", VALID_SHA512_SRI),
        ("https://user@registry.npmjs.org/pkg/-/pkg-1.0.0.tgz", VALID_SHA512_SRI),
        ("https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz?download=1", VALID_SHA512_SRI),
        ("https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz#fragment", VALID_SHA512_SRI),
        ("https://registry.npmjs.org/pkg/-/pkg-1.0.0", VALID_SHA512_SRI),
        ("https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz", "x"),
        ("https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz", "sha512-abc"),
        (
            "https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz",
            "sha256-" + base64.b64encode(bytes(32)).decode("ascii"),
        ),
        (
            "https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz",
            "sha512-" + base64.b64encode(bytes(32)).decode("ascii"),
        ),
    ],
    ids=[
        "file-url",
        "http-url",
        "wrong-host",
        "credentials",
        "query",
        "fragment",
        "not-tarball",
        "placeholder-integrity",
        "invalid-base64",
        "wrong-algorithm",
        "wrong-digest-length",
    ],
)
def test_registry_artifact_guard_rejects_untrusted_source_or_sri(
    resolved: str,
    integrity: str,
) -> None:
    with pytest.raises(AssertionError):
        _assert_registry_artifact(
            "synthetic node_modules/pkg",
            {"resolved": resolved, "integrity": integrity},
        )


def test_every_ci_node_job_activates_and_verifies_exact_npm() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    node_jobs = [block for block in _ci_job_blocks(workflow) if "actions/setup-node@" in block]
    for job in node_jobs:
        normalized = re.sub(r"\s+", " ", job)
        assert "corepack enable npm && corepack prepare npm@10.9.4 --activate" in normalized
        assert 'test "$(npm --version)" = "10.9.4"' in normalized

    assert len(node_jobs) == 4


def test_every_npm_project_enforces_exact_engine_and_strict_mode() -> None:
    project_paths = (
        ROOT / "frontend",
        ROOT / "frontend" / "tools" / "openapi-generator",
    )

    for project_path in project_paths:
        manifest = json.loads((project_path / "package.json").read_text(encoding="utf-8"))
        assert manifest["packageManager"] == "npm@10.9.4"
        assert manifest["engines"]["npm"] == "10.9.4"
        assert (project_path / ".npmrc").read_text(encoding="utf-8") == "engine-strict=true\n"
