import base64
import binascii
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

SPEC = importlib.util.spec_from_file_location(
    "generate_dependency_licenses",
    ROOT / "scripts" / "generate_dependency_licenses.py",
)
assert SPEC is not None and SPEC.loader is not None
generate_dependency_licenses = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_dependency_licenses)

VALID_SHA512_SRI = "sha512-" + base64.b64encode(bytes(64)).decode("ascii")
SETUP_NODE_PREFIX = "actions/setup-node@"
NPM_ACTIVATION_COMMAND = "corepack enable npm && corepack prepare npm@10.9.4 --activate"
NPM_VERSION_COMMAND = 'test "$(npm --version)" = "10.9.4"'


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


def _assert_exact_run_step(step: object, expected_command: str, context: str) -> None:
    assert isinstance(step, dict), f"{context} must be a step mapping"
    assert set(step) == {"run"}, f"{context} must be a dedicated run-only step"
    run = step["run"]
    assert isinstance(run, str), f"{context} run value must be a string"
    assert " ".join(run.split()) == expected_command, f"{context} command must be exact"


def _assert_ci_node_custody(source: str, *, expected_node_jobs: int = 4) -> None:
    workflow = yaml.safe_load(source)
    assert isinstance(workflow, dict), "CI workflow must be a mapping"
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "CI workflow must contain a jobs mapping"

    node_job_count = 0
    for job_name, job in jobs.items():
        if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
            continue
        steps = job["steps"]
        setup_indices = [
            index
            for index, step in enumerate(steps)
            if isinstance(step, dict)
            and isinstance(step.get("uses"), str)
            and step["uses"].startswith(SETUP_NODE_PREFIX)
        ]
        if not setup_indices:
            continue
        node_job_count += 1

        for setup_index in setup_indices:
            assert setup_index + 2 < len(steps), (
                f"{job_name} must place two custody steps directly after setup-node"
            )
            _assert_exact_run_step(
                steps[setup_index + 1],
                NPM_ACTIVATION_COMMAND,
                f"{job_name} npm activation",
            )
            _assert_exact_run_step(
                steps[setup_index + 2],
                NPM_VERSION_COMMAND,
                f"{job_name} npm version gate",
            )

    assert node_job_count == expected_node_jobs


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
    _assert_ci_node_custody(workflow)


@pytest.mark.parametrize(
    "workflow",
    [
        """
jobs:
  comments:
    # - uses: actions/setup-node@v6
    # - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
    # - run: test "$(npm --version)" = "10.9.4"
    steps:
      - run: echo safe
""",
        """
jobs:
  metadata:
    steps:
      - uses: actions/setup-node@v6
      - name: corepack enable npm && corepack prepare npm@10.9.4 --activate
        env:
          VERIFY: test "$(npm --version)" = "10.9.4"
      - run: npm ci
""",
        """
jobs:
  shell-comments:
    steps:
      - uses: actions/setup-node@v6
      - run: |
          # corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: |
          # test "$(npm --version)" = "10.9.4"
      - run: npm ci
""",
        """
jobs:
  misplaced:
    uses: actions/setup-node@v6
    steps:
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
""",
        """
jobs:
  non-mapping-step:
    steps:
      - actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
""",
        """
jobs:
  late-activation:
    steps:
      - uses: actions/setup-node@v6
      - run: npm ci
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
""",
        """
jobs:
  late-version-gate:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: npm ci
      - run: test "$(npm --version)" = "10.9.4"
""",
        """
jobs:
  late-version-in-same-run:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: npm ci && test "$(npm --version)" = "10.9.4"
""",
        """
jobs:
  gate-before-activation:
    steps:
      - uses: actions/setup-node@v6
      - run: test "$(npm --version)" = "10.9.4"
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: npm ci
""",
        """
jobs:
  neutralized-gate:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4" || true
      - run: npm ci
""",
        """
jobs:
  fallback-gate:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4" || echo ignored
      - run: npm ci
""",
        """
jobs:
  printed-evidence:
    steps:
      - uses: actions/setup-node@v6
      - run: printf '%s\\n' 'corepack enable npm && corepack prepare npm@10.9.4 --activate'
      - run: echo 'test "$(npm --version)" = "10.9.4"'
      - run: npm ci
""",
        """
jobs:
  literal-substitution:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test '$(npm --version)' = '10.9.4'
      - run: npm ci
""",
        """
jobs:
  piped-gate:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4" | cat
      - run: npm ci
""",
        """
jobs:
  non-enforcing-activation:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm ; corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
      - run: npm ci
""",
        """
jobs:
  hidden-workload:
    steps:
      - uses: actions/setup-node@v6
      - run: $(printf npm) ci
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
      - run: npm test
""",
        """
jobs:
  environment-prefixed-workload:
    steps:
      - uses: actions/setup-node@v6
      - run: CI=true npm ci
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
      - run: npm test
""",
        """
jobs:
  indirect-bypass:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: true && test "$(npm --version)" = "10.9.4" || true
      - run: npm ci
""",
        """
jobs:
  prefixed-activation:
    steps:
      - uses: actions/setup-node@v6
      - run: echo ready && corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
      - run: npm ci
""",
        """
jobs:
  suffixed-gate:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4" && echo extra
      - run: npm ci
""",
        """
jobs:
  intervening-step:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: echo decoy
      - run: test "$(npm --version)" = "10.9.4"
      - run: npm ci
""",
        """
jobs:
  activation-env-override:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
        env:
          COREPACK_HOME: /tmp/decoy
      - run: test "$(npm --version)" = "10.9.4"
      - run: npm ci
""",
        """
jobs:
  gate-continue-on-error:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
        continue-on-error: true
      - run: npm ci
""",
        """
jobs:
  gate-shell-override:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: test "$(npm --version)" = "10.9.4"
        shell: python
      - run: npm ci
""",
        """
jobs:
  missing-activation:
    steps:
      - uses: actions/setup-node@v6
      - run: test "$(npm --version)" = "10.9.4"
      - run: npm ci
""",
        """
jobs:
  missing-version-gate:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@10.9.4 --activate
      - run: npm ci
""",
        """
jobs:
  wrong-version:
    steps:
      - uses: actions/setup-node@v6
      - run: corepack enable npm && corepack prepare npm@11.0.0 --activate
      - run: test "$(npm --version)" = "11.0.0"
      - run: npm ci
""",
    ],
    ids=[
        "evidence-only-in-comments",
        "evidence-only-in-name-or-env",
        "evidence-only-in-shell-comments",
        "uses-at-job-level",
        "uses-in-non-mapping-step",
        "activation-after-npm-ci",
        "version-gate-after-npm-ci",
        "version-gate-after-npm-ci-in-same-run",
        "gate-before-activation",
        "gate-neutralized-by-or-true",
        "gate-neutralized-by-or-echo",
        "echo-or-printf-evidence",
        "command-substitution-used-as-data",
        "gate-neutralized-by-pipeline",
        "activation-not-joined-by-and",
        "command-substitution-workload-before-custody",
        "environment-prefixed-workload-before-custody",
        "indirect-gate-bypass",
        "activation-has-extra-command",
        "gate-has-extra-command",
        "intervening-step",
        "activation-env-override",
        "gate-continue-on-error",
        "gate-shell-override",
        "missing-activation",
        "missing-version-gate",
        "wrong-version",
    ],
)
def test_ci_node_custody_rejects_non_executable_or_late_evidence(workflow: str) -> None:
    with pytest.raises(AssertionError):
        _assert_ci_node_custody(workflow, expected_node_jobs=1)


def test_ci_node_custody_accepts_valid_multiline_run_steps() -> None:
    workflow = """
jobs:
  valid:
    steps:
      - uses: actions/setup-node@v6
      - run: >-
          corepack enable npm &&
          corepack prepare npm@10.9.4 --activate
      - run: >-
          test "$(npm --version)"
          = "10.9.4"
      - run: npm ci
"""

    _assert_ci_node_custody(workflow, expected_node_jobs=1)


def test_ci_node_custody_rejects_combined_same_run_commands() -> None:
    workflow = """
jobs:
  valid:
    steps:
      - uses: actions/setup-node@v6
      - run: |
          corepack enable npm &&
          corepack prepare npm@10.9.4 --activate &&
          test "$(npm --version)" = "10.9.4" &&
          npm ci
"""

    with pytest.raises(AssertionError):
        _assert_ci_node_custody(workflow, expected_node_jobs=1)


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
