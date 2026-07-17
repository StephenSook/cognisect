"""Frozen benchmark metrics and compiler-ablation contracts."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from cognisect.benchmark import (
    BenchmarkModelResult,
    RankedEvaluationItem,
    build_deterministic_benchmark_report,
    build_live_benchmark_report,
    leave_one_question_out_majority,
    run_live_model_calls,
    score_ranked_predictions,
)
from cognisect.model_policy import InstructionalNotePlanV1, TerraAnalysisV1
from cognisect.models import RuleInstanceV1, RuleMappingV1, TemplateId

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads(
    (ROOT / "data" / "evaluation" / "manifest.v1.json").read_text(encoding="utf-8")
)


def test_leave_one_question_out_majority_never_trains_on_the_scored_question() -> None:
    predictions = leave_one_question_out_majority(MANIFEST["records"])

    assert predictions == {
        "eval-ea-001": (
            "add_subtrahend",
            "keep_minuend_sign",
            "subtract_magnitudes",
            "ignore_subtrahend_sign",
        ),
        "eval-ea-002": (
            "add_subtrahend",
            "keep_minuend_sign",
            "absolute_difference",
            "subtract_magnitudes",
        ),
        "eval-ea-003": (
            "add_subtrahend",
            "keep_minuend_sign",
            "absolute_difference",
            "subtract_magnitudes",
        ),
        "eval-ea-004": (
            "add_subtrahend",
            "absolute_difference",
            "subtract_magnitudes",
            "keep_minuend_sign",
        ),
        "eval-ea-005": (
            "add_subtrahend",
            "subtract_magnitudes",
            "keep_minuend_sign",
            "ignore_subtrahend_sign",
        ),
        "eval-ea-006": (
            "add_subtrahend",
            "absolute_difference",
            "keep_minuend_sign",
            "ignore_subtrahend_sign",
        ),
    }


def test_ranked_metrics_include_abstentions_in_coverage_and_recall_denominators() -> None:
    metrics = score_ranked_predictions(
        [
            RankedEvaluationItem(
                manifest_id="one",
                expected=("add_subtrahend", "absolute_difference"),
                predicted=("add_subtrahend", "keep_minuend_sign"),
            ),
            RankedEvaluationItem(
                manifest_id="two",
                expected=("subtract_magnitudes", "keep_minuend_sign"),
                predicted=None,
            ),
        ]
    )

    assert metrics == {
        "coverage": 0.5,
        "abstention_rate": 0.5,
        "recall_at_1": 0.5,
        "recall_at_2": 0.5,
        "recall_at_4": 0.5,
        "mrr": 0.5,
        "exact_set_rate": 0.0,
        "selective_risk_at_1": 0.0,
    }


def test_deterministic_report_keeps_fixture_tier_and_interactive_claim_boundary() -> None:
    report = build_deterministic_benchmark_report(MANIFEST)

    assert report["schema_version"] == "cognisect.benchmark-report.v1"
    assert report["evaluation_kind"] == "frozen_educator_authored_comparison"
    assert report["record_count"] == 6
    assert report["tiers"] == {"educator_authored": 6}
    assert report["learner_responses_collected"] == 0
    assert report["comparisons"]["leave_one_question_out_majority_label"]["status"] == (
        "completed"
    )
    assert report["comparisons"]["full_interactive_workflow"] == {
        "status": "not_run",
        "reason": "no real learner responses were collected",
    }
    assert report["model_calls_made"] == 0
    assert report["model_results_status"] == "not_run"
    assert report["items"] == []
    assert "no model-accuracy generalization" in report["claim_scope"].lower()


def _mapping(template_ids: list[TemplateId]) -> RuleMappingV1:
    return RuleMappingV1(
        schema_version="rule_mapping.v1",
        hypotheses=[
            RuleInstanceV1(
                template_id=template_id,
                evidence_refs=["observed_work"],
                description=f"Fixture description for {template_id}.",
                rank=rank,
            )
            for rank, template_id in enumerate(template_ids, start=1)
        ],
    )


def _model_result(
    manifest_id: str,
    purpose: str,
    template_ids: list[TemplateId] | None,
    ordinal: int,
) -> BenchmarkModelResult:
    model_id = f"gpt-5.6-{purpose}"
    return BenchmarkModelResult(
        manifest_id=manifest_id,
        purpose=purpose,
        mapping=_mapping(template_ids) if template_ids is not None else None,
        schema_valid=template_ids is not None,
        requested_model_id=model_id,
        returned_model_id=model_id,
        request_id=f"resp-{purpose}-{ordinal}",
        latency_ms=100 + ordinal,
        input_tokens=1_200,
        output_tokens=80,
        reasoning_tokens=20,
        cached_input_tokens=1_000,
        cache_write_input_tokens=0,
        cost_usd=Decimal("0.001000"),
        prompt_hash=f"{ordinal:064x}",
        prompt_cache_key=f"cognisect.analysis_prompt.v2.{purpose}",
        failure=None if template_ids is not None else "malformed_output",
    )


def test_live_report_reuses_terra_artifact_for_baselines_and_scores_sol_separately() -> None:
    results: list[BenchmarkModelResult] = []
    for ordinal, record in enumerate(MANIFEST["records"], start=1):
        labels = record["evaluation_only"]["expected_template_ids"]
        results.append(_model_result(record["manifest_id"], "terra", labels, ordinal))
        results.append(_model_result(record["manifest_id"], "sol", labels, ordinal + 10))

    report = build_live_benchmark_report(
        MANIFEST,
        protocol_sha256="a" * 64,
        generated_at="2026-07-17T06:00:00Z",
        model_results=results,
    )

    assert report["model_calls_made"] == 12
    assert report["model_results_status"] == "completed"
    direct = report["comparisons"]["direct_gpt_5_6_structured_classification"]
    assert direct["shared_artifact"] == "terra_rule_mapping"
    assert direct["metrics"]["recall_at_1"] == 1.0
    without_compiler = report["comparisons"][
        "gpt_5_6_hypothesis_mapping_without_compiler"
    ]
    assert without_compiler["compiler_used"] is False
    assert without_compiler["registry_acceptance_rate"] == 1.0
    with_compiler = report["comparisons"][
        "gpt_5_6_plus_compiler_without_learner_response"
    ]
    assert with_compiler["separating_probe_rate"] == 1.0
    assert with_compiler["deterministic_reproduction_rate"] == 1.0
    assert with_compiler["learner_responses_collected"] == 0
    assert report["model_comparison"]["terra"]["metrics"]["mrr"] == 1.0
    assert report["model_comparison"]["sol"]["metrics"]["mrr"] == 1.0
    assert report["telemetry"]["total_cost_usd"] == "0.012000"
    assert report["telemetry"]["latency_ms"] == {"p50": 106, "p95": 116, "p99": 116}
    assert len(report["items"]) == 6
    rendered = json.dumps(report)
    assert "observed_work" not in rendered
    assert "learner_token" not in rendered
    assert "api_key" not in rendered


def _response(payload: object, *, model: str, request_id: str) -> SimpleNamespace:
    text = payload.model_dump_json() if hasattr(payload, "model_dump_json") else str(payload)
    return SimpleNamespace(
        id=request_id,
        model=model,
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text=text)],
            )
        ],
        usage=SimpleNamespace(
            input_tokens=1_100,
            output_tokens=90,
            input_tokens_details=SimpleNamespace(cached_tokens=1_000, cache_write_tokens=0),
            output_tokens_details=SimpleNamespace(reasoning_tokens=20),
        ),
    )


@pytest.mark.asyncio
async def test_live_calls_use_two_exact_frozen_contracts_per_record_without_gold_labels() -> None:
    calls: list[dict[str, object]] = []

    class Responses:
        async def create(self, **kwargs):
            calls.append(kwargs)
            purpose = "terra" if kwargs["model"] == "gpt-5.6-terra" else "sol"
            record_index = (len(calls) - 1) // 2
            labels = MANIFEST["records"][record_index]["evaluation_only"][
                "expected_template_ids"
            ]
            mapping = _mapping(labels)
            payload = (
                TerraAnalysisV1(
                    schema_version="terra_analysis.v1",
                    mapping=mapping,
                    instructional_note_plan=InstructionalNotePlanV1(
                        schema_version="instructional_note_plan.v1",
                        observation="multiple_hypotheses_fit_observed_work",
                        teacher_action="review_compiled_probe",
                    ),
                )
                if purpose == "terra"
                else mapping
            )
            return _response(
                payload,
                model=kwargs["model"],
                request_id=f"resp-{purpose}-{record_index + 1}",
            )

    client = SimpleNamespace(responses=Responses())
    results = await run_live_model_calls(MANIFEST, client=client)

    assert len(results) == len(calls) == 12
    assert [result.purpose for result in results[:4]] == ["terra", "sol", "terra", "sol"]
    assert all(result.schema_valid for result in results)
    assert all(call["store"] is False for call in calls)
    assert all("reasoning" not in call and "include" not in call for call in calls)
    assert all(call["text"]["format"]["strict"] is True for call in calls)
    assert all("expected_template_ids" not in call["input"] for call in calls)
    assert all("label_source" not in call["input"] for call in calls)


@pytest.mark.asyncio
async def test_live_calls_fail_closed_on_returned_model_mismatch() -> None:
    class Responses:
        async def create(self, **_kwargs):
            mapping = _mapping(["add_subtrahend", "absolute_difference"])
            payload = TerraAnalysisV1(
                schema_version="terra_analysis.v1",
                mapping=mapping,
                instructional_note_plan=InstructionalNotePlanV1(
                    schema_version="instructional_note_plan.v1",
                    observation="multiple_hypotheses_fit_observed_work",
                    teacher_action="review_compiled_probe",
                ),
            )
            return _response(payload, model="wrong-model", request_id="resp-wrong")

    with pytest.raises(RuntimeError, match="returned model did not match"):
        await run_live_model_calls(MANIFEST, client=SimpleNamespace(responses=Responses()))
