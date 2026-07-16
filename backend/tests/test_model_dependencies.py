"""Task 3 dependency and frozen model-price contracts."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_task_three_runtime_dependencies_are_exactly_pinned() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert {
        "openai==2.45.0",
        "langgraph==1.2.9",
        "langgraph-checkpoint-postgres==3.1.0",
    } <= set(project["project"]["dependencies"])


def test_frozen_price_table_uses_exact_models_and_official_rates() -> None:
    from cognisect.model_policy import MODEL_IDS, PRICE_TABLE

    assert MODEL_IDS == {
        "luna": "gpt-5.6-luna",
        "terra": "gpt-5.6-terra",
        "sol": "gpt-5.6-sol",
    }
    assert PRICE_TABLE.version == "openai-pricing-2026-07-16.v1"
    assert PRICE_TABLE.retrieved_on.isoformat() == "2026-07-16"
    assert PRICE_TABLE.usd_per_million == {
        "gpt-5.6-luna": {"input": "1.00", "cached_input": "0.10", "output": "6.00"},
        "gpt-5.6-terra": {"input": "2.50", "cached_input": "0.25", "output": "15.00"},
        "gpt-5.6-sol": {"input": "5.00", "cached_input": "0.50", "output": "30.00"},
    }
