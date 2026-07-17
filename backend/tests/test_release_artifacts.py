"""Release documentation, CI topology, and deployment-boundary contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_PUBLIC_DOCS = {
    "docs/ARCHITECTURE.md",
    "docs/DATASET_CARD.md",
    "docs/EVALUATION.md",
    "docs/SECURITY.md",
    "docs/BUILD_LOG.md",
    "docs/DEPLOYMENT.md",
    "docs/FACT_SHEET.md",
    "docs/EDUCATOR_REVIEW.md",
}


def test_required_public_release_docs_exist_and_reject_unearned_claims() -> None:
    for relative_path in REQUIRED_PUBLIC_DOCS:
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        text = path.read_text(encoding="utf-8").lower()
        assert "confirmed misconception" not in text
        assert "exact diagnosis" not in text


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
