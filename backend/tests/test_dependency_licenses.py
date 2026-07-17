import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

SPEC = importlib.util.spec_from_file_location(
    "generate_dependency_licenses",
    ROOT / "scripts" / "generate_dependency_licenses.py",
)
assert SPEC is not None and SPEC.loader is not None
generate_dependency_licenses = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_dependency_licenses)


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
            assert package.get("resolved"), f"{lock_path}: {package_path} lacks resolved"
            assert package.get("integrity"), f"{lock_path}: {package_path} lacks integrity"


def test_every_ci_node_job_activates_and_verifies_exact_npm() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    node_jobs = 0
    for job in workflow["jobs"].values():
        steps = job["steps"]
        if not any("actions/setup-node" in step.get("uses", "") for step in steps):
            continue
        node_jobs += 1
        commands = [step.get("run", "") for step in steps]
        assert "corepack enable npm && corepack prepare npm@10.9.4 --activate" in commands
        assert 'test "$(npm --version)" = "10.9.4"' in commands

    assert node_jobs == 4


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
