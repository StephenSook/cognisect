"""Release documentation, CI topology, and deployment-boundary contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_PUBLIC_DOCS = {
    "docs/ARCHITECTURE.md",
    "docs/DATASET_CARD.md",
    "docs/EVALUATION.md",
    "docs/SECURITY.md",
    "docs/DEPLOYMENT.md",
    "docs/DEPENDENCY_LICENSES.md",
    "docs/specs/data-tiers.md",
    "docs/specs/evidence-contract.md",
    "docs/specs/rule-registry-v1.md",
    "docs/specs/state-machine.md",
}

FORBIDDEN_PUBLIC_PROCESS_ARTIFACTS = {
    "PLAN.md",
    "docs/BUILD_LOG.md",
    "docs/EDUCATOR_REVIEW.md",
    "docs/FACT_SHEET.md",
    "docs/SUBMISSION_COPY.md",
    "docs/superpowers/plans/2026-07-17-release-evidence-gates.md",
}


def test_required_public_release_docs_exist_and_reject_unearned_claims() -> None:
    for relative_path in REQUIRED_PUBLIC_DOCS:
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        text = path.read_text(encoding="utf-8").lower()
        assert "confirmed misconception" not in text
        assert "exact diagnosis" not in text


def test_internal_process_artifacts_are_not_in_the_public_repository() -> None:
    for relative_path in FORBIDDEN_PUBLIC_PROCESS_ARTIFACTS:
        assert not (ROOT / relative_path).exists(), relative_path


def test_readme_has_product_visual_and_github_architecture() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/assets/cognisect-product-overview.png" in readme
    assert (ROOT / "docs" / "assets" / "cognisect-product-overview.png").is_file()
    assert "```mermaid" in readme
    assert "https://cognisect.vercel.app/lab" in readme


def test_ci_has_six_named_jobs_and_no_sqlite() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    expected_job_keys = {
        "  hygiene:",
        "  backend-quality:",
        "  backend-tests:",
        "  frontend:",
        "  accessibility-e2e:",
        "  contracts-containers:",
    }

    assert {line for line in workflow.splitlines() if line in expected_job_keys} == (
        expected_job_keys
    )
    assert workflow.count("    name:") == 6
    assert workflow.count("cache-suffix: ${{ github.job }}") == 5
    assert "fetch-depth: 0" in workflow
    assert (
        "gitleaks/gitleaks-action@ff98106e4c7b2bc287b24eaf42907196329070c7"
        in workflow
    )
    assert "sqlite" not in workflow.lower()


def test_playwright_backend_launcher_uses_the_runner_cache_directory() -> None:
    config = (ROOT / "frontend" / "playwright.config.ts").read_text(encoding="utf-8")

    assert 'command: "uv run python backend/tests/run_frontend_server.py"' in config
    assert "process.env.UV_CACHE_DIR" in config
    assert "UV_CACHE_DIR=/private/tmp" not in config


def test_deployment_manifests_do_not_embed_credentials_or_demo_bypasses() -> None:
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    vercel = (ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8")
    combined = f"{render}\n{vercel}".lower()

    assert "sync: false" in render
    assert "demo_mode" not in combined
    assert "auth_bypass" not in combined
    assert "key: OPENAI_API_KEY" in render
    assert "value:" not in "\n".join(
        line for line in render.splitlines() if "OPENAI_API_KEY" in line
    )


def test_preview_blueprint_defaults_to_free_resources_and_documents_limits() -> None:
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    deployment = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")

    assert render.count("plan: free") == 2
    assert "plan: starter" not in render
    assert "plan: basic-256mb" not in render
    assert (
        'dockerCommand: "/bin/sh -c ./scripts/migrate.sh && exec ./scripts/run-backend.sh"'
        in render
    )
    assert "preDeployCommand:" not in render
    assert "time-limited public preview" in deployment
    assert "cognisect.vercel.app" in deployment


def test_vercel_link_metadata_is_ignored() -> None:
    ignored_paths = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".vercel/" in ignored_paths
