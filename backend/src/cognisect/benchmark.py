"""Claim-limited metrics for the frozen educator-authored benchmark tier."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from typing import Literal, Protocol, cast

from pydantic import BaseModel

from cognisect.api_models import CreateCaseRequest
from cognisect.compiler import CompiledProbe, compile_probe, reproduce_probe_hash
from cognisect.interpreter import REGISTRY_TEMPLATE_IDS, accept_hypotheses
from cognisect.model_analyzer import (
    provider_json_schema,
    response_is_refusal,
    response_schema_name,
    single_output_text,
    usage_from_response,
)
from cognisect.model_policy import (
    MODEL_IDS,
    TerraAnalysisV1,
    TokenUsage,
    calculate_cost_usd,
    returned_model_is_allowed,
)
from cognisect.models import RuleMappingV1, TemplateId
from cognisect.prompts.analysis_v1 import allowed_evidence_refs, build_prompt

_MIN_LEAVE_ONE_OUT_RECORDS = 2
_MAX_OUTPUT_TOKENS = 1_200


@dataclass(frozen=True, slots=True)
class RankedEvaluationItem:
    """One gold label set and an optional ranked prediction."""

    manifest_id: str
    expected: tuple[TemplateId, ...]
    predicted: tuple[TemplateId, ...] | None


@dataclass(frozen=True, slots=True)
class BenchmarkModelResult:
    """One sanitized Terra or Sol call result for one frozen manifest record."""

    manifest_id: str
    purpose: Literal["terra", "sol"]
    mapping: RuleMappingV1 | None
    schema_valid: bool
    requested_model_id: str
    returned_model_id: str | None
    response_id: str | None
    request_id: str | None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    cost_usd: Decimal
    prompt_hash: str
    prompt_cache_key: str
    failure: str | None


class _ResponsesResource(Protocol):
    async def create(self, **kwargs: object) -> object: ...


class BenchmarkResponsesClient(Protocol):
    """Small official-client surface needed by the benchmark runner."""

    @property
    def responses(self) -> _ResponsesResource:
        """Return the official Responses API resource."""
        ...


def _rate(numerator: float, denominator: int) -> float:
    if denominator <= 0:
        msg = "evaluation metrics require at least one record"
        raise ValueError(msg)
    return round(numerator / denominator, 6)


def score_ranked_predictions(items: Sequence[RankedEvaluationItem]) -> dict[str, float]:
    """Score ranked multi-label outputs while counting abstentions in all denominators."""
    count = len(items)
    if count == 0:
        msg = "ranked evaluation requires at least one item"
        raise ValueError(msg)
    covered = 0
    hits = {1: 0, 2: 0, 4: 0}
    reciprocal_rank = 0.0
    exact_sets = 0
    covered_top_one_errors = 0
    for item in items:
        if item.predicted is None:
            continue
        covered += 1
        expected = set(item.expected)
        for cutoff in hits:
            if expected.intersection(item.predicted[:cutoff]):
                hits[cutoff] += 1
        first_relevant = next(
            (rank for rank, value in enumerate(item.predicted, start=1) if value in expected),
            None,
        )
        if first_relevant is not None:
            reciprocal_rank += 1 / first_relevant
        if set(item.predicted) == expected:
            exact_sets += 1
        if not item.predicted or item.predicted[0] not in expected:
            covered_top_one_errors += 1
    return {
        "coverage": _rate(covered, count),
        "abstention_rate": _rate(count - covered, count),
        "recall_at_1": _rate(hits[1], count),
        "recall_at_2": _rate(hits[2], count),
        "recall_at_4": _rate(hits[4], count),
        "mrr": _rate(reciprocal_rank, count),
        "exact_set_rate": _rate(exact_sets, count),
        "selective_risk_at_1": _rate(covered_top_one_errors, covered) if covered else 0.0,
    }


def _record_fields(record: Mapping[str, object]) -> tuple[str, str, tuple[TemplateId, ...]]:
    manifest_id = record.get("manifest_id")
    question_id = record.get("question_id")
    evaluation_only = record.get("evaluation_only")
    if not isinstance(manifest_id, str) or not isinstance(question_id, str):
        msg = "benchmark records require string manifest_id and question_id"
        raise TypeError(msg)
    if not isinstance(evaluation_only, Mapping):
        msg = "benchmark records require evaluation_only labels"
        raise TypeError(msg)
    raw_labels = evaluation_only.get("expected_template_ids")
    if not isinstance(raw_labels, list) or not raw_labels:
        msg = "benchmark records require at least one expected template"
        raise ValueError(msg)
    labels: list[TemplateId] = []
    for raw_label in raw_labels:
        if raw_label not in REGISTRY_TEMPLATE_IDS:
            msg = "benchmark labels must belong to the closed registry"
            raise ValueError(msg)
        labels.append(cast("TemplateId", raw_label))
    return manifest_id, question_id, tuple(labels)


def leave_one_question_out_majority(
    records: Sequence[Mapping[str, object]],
) -> dict[str, tuple[TemplateId, ...]]:
    """Rank label frequency without using records from the scored question."""
    parsed = [_record_fields(record) for record in records]
    if len(parsed) < _MIN_LEAVE_ONE_OUT_RECORDS:
        msg = "leave-one-question-out evaluation requires at least two records"
        raise ValueError(msg)
    registry_order = {template_id: index for index, template_id in enumerate(REGISTRY_TEMPLATE_IDS)}
    result: dict[str, tuple[TemplateId, ...]] = {}
    for manifest_id, question_id, _expected in parsed:
        counts: Counter[TemplateId] = Counter(
            label
            for _other_id, other_question, labels in parsed
            if other_question != question_id
            for label in labels
        )
        if not counts:
            msg = "question grouping left no training records"
            raise ValueError(msg)
        ranked = sorted(
            REGISTRY_TEMPLATE_IDS,
            key=lambda template_id: (-counts[template_id], registry_order[template_id]),
        )
        result[manifest_id] = tuple(ranked[:4])
    return result


def build_deterministic_benchmark_report(manifest: Mapping[str, object]) -> dict[str, object]:
    """Build the no-network portion of the frozen comparison report."""
    raw_records = manifest.get("records")
    claim_scope = manifest.get("claim_scope")
    if not isinstance(raw_records, list) or not all(
        isinstance(record, Mapping) for record in raw_records
    ):
        msg = "evaluation manifest records must be objects"
        raise ValueError(msg)
    if not isinstance(claim_scope, str):
        msg = "evaluation manifest requires a claim scope"
        raise TypeError(msg)
    records = cast("list[Mapping[str, object]]", raw_records)
    majority = leave_one_question_out_majority(records)
    ranked_items = [
        RankedEvaluationItem(
            manifest_id=manifest_id,
            expected=expected,
            predicted=majority[manifest_id],
        )
        for manifest_id, _question_id, expected in map(_record_fields, records)
    ]
    tier_counts: Counter[str] = Counter()
    for record in records:
        tier = record.get("tier")
        if not isinstance(tier, str):
            msg = "evaluation records require a string tier"
            raise TypeError(msg)
        tier_counts[tier] += 1
    return {
        "schema_version": "cognisect.benchmark-report.v1",
        "evaluation_kind": "frozen_educator_authored_comparison",
        "record_count": len(records),
        "tiers": dict(sorted(tier_counts.items())),
        "learner_responses_collected": 0,
        "model_calls_made": 0,
        "model_results_status": "not_run",
        "comparisons": {
            "leave_one_question_out_majority_label": {
                "status": "completed",
                "model_calls": 0,
                "metrics": score_ranked_predictions(ranked_items),
            },
            "direct_gpt_5_6_structured_classification": {"status": "not_run"},
            "gpt_5_6_hypothesis_mapping_without_compiler": {"status": "not_run"},
            "gpt_5_6_plus_compiler_without_learner_response": {"status": "not_run"},
            "full_interactive_workflow": {
                "status": "not_run",
                "reason": "no real learner responses were collected",
            },
        },
        "items": [],
        "claim_scope": (
            f"{claim_scope} The six educator-authored fixtures support no model-accuracy "
            "generalization."
        ),
    }


def _nearest_rank_percentile(values: Sequence[int], percentile: float) -> int:
    if not values:
        msg = "latency percentiles require at least one call"
        raise ValueError(msg)
    ordered = sorted(values)
    rank = max(1, ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _model_result_metrics(
    parsed_records: Sequence[tuple[str, str, tuple[TemplateId, ...]]],
    results: Mapping[str, BenchmarkModelResult],
) -> tuple[dict[str, float], list[RankedEvaluationItem]]:
    items = [
        RankedEvaluationItem(
            manifest_id=manifest_id,
            expected=expected,
            predicted=(
                tuple(
                    hypothesis.template_id
                    for hypothesis in cast("RuleMappingV1", results[manifest_id].mapping).hypotheses
                )
                if results[manifest_id].mapping is not None
                else None
            ),
        )
        for manifest_id, _question_id, expected in parsed_records
    ]
    return score_ranked_predictions(items), items


def _validate_model_result_matrix(
    parsed_records: Sequence[tuple[str, str, tuple[TemplateId, ...]]],
    model_results: Sequence[BenchmarkModelResult],
) -> dict[str, dict[str, BenchmarkModelResult]]:
    expected_ids = {manifest_id for manifest_id, _question_id, _expected in parsed_records}
    matrix: dict[str, dict[str, BenchmarkModelResult]] = {"terra": {}, "sol": {}}
    for result in model_results:
        if result.manifest_id not in expected_ids:
            msg = "model result references an unknown manifest record"
            raise ValueError(msg)
        purpose_results = matrix[result.purpose]
        if result.manifest_id in purpose_results:
            msg = "model result matrix contains a duplicate call"
            raise ValueError(msg)
        purpose_results[result.manifest_id] = result
    if any(set(purpose_results) != expected_ids for purpose_results in matrix.values()):
        msg = "every frozen record requires exactly one Terra and one Sol call"
        raise ValueError(msg)
    return matrix


def _registry_metrics(results: Sequence[BenchmarkModelResult]) -> dict[str, float]:
    accepted_items = 0
    accepted_rules = 0
    requested_rules = 0
    for result in results:
        if result.mapping is None:
            continue
        accepted = accept_hypotheses(result.mapping)
        requested_rules += len(result.mapping.hypotheses)
        accepted_rules += len(accepted)
        if len(accepted) == len(result.mapping.hypotheses):
            accepted_items += 1
    count = len(results)
    return {
        "schema_valid_output_rate": _rate(
            sum(result.schema_valid for result in results), count
        ),
        "registry_acceptance_rate": _rate(accepted_items, count),
        "unique_semantic_rule_rate": (
            _rate(accepted_rules, requested_rules) if requested_rules else 0.0
        ),
    }


def build_live_benchmark_report(  # noqa: PLR0915 - one explicit report assembly boundary.
    manifest: Mapping[str, object],
    *,
    protocol_sha256: str,
    generated_at: str,
    model_results: Sequence[BenchmarkModelResult],
) -> dict[str, object]:
    """Combine sanitized frozen calls with deterministic mapping/compiler metrics."""
    report = build_deterministic_benchmark_report(manifest)
    raw_records = manifest.get("records")
    if not isinstance(raw_records, list):
        msg = "evaluation manifest records must be a list"
        raise TypeError(msg)
    records = cast("list[Mapping[str, object]]", raw_records)
    parsed_records = [_record_fields(record) for record in records]
    matrix = _validate_model_result_matrix(parsed_records, model_results)
    terra_results = matrix["terra"]
    sol_results = matrix["sol"]
    terra_metrics, terra_items = _model_result_metrics(parsed_records, terra_results)
    sol_metrics, _sol_items = _model_result_metrics(parsed_records, sol_results)
    ordered_terra = [terra_results[manifest_id] for manifest_id, _, _ in parsed_records]
    ordered_sol = [sol_results[manifest_id] for manifest_id, _, _ in parsed_records]

    separating = 0
    reproduced = 0
    compiled_hashes: dict[str, str | None] = {}
    for manifest_id, _question_id, _expected in parsed_records:
        result = terra_results[manifest_id]
        record = next(record for record in records if record["manifest_id"] == manifest_id)
        runtime_input = record.get("runtime_input")
        if result.mapping is None or not isinstance(runtime_input, Mapping):
            compiled_hashes[manifest_id] = None
            continue
        problem = runtime_input.get("problem")
        if not isinstance(problem, Mapping):
            msg = "runtime input requires a problem object"
            raise TypeError(msg)
        a = problem.get("a")
        b = problem.get("b")
        if type(a) is not int or type(b) is not int:
            msg = "benchmark problem operands must be strict integers"
            raise TypeError(msg)
        probe = compile_probe(result.mapping, a, b)
        if not isinstance(probe, CompiledProbe):
            compiled_hashes[manifest_id] = None
            continue
        separating += 1
        if reproduce_probe_hash(probe) == probe.specification_hash:
            reproduced += 1
        compiled_hashes[manifest_id] = probe.specification_hash

    comparisons = cast("dict[str, object]", report["comparisons"])
    comparisons["direct_gpt_5_6_structured_classification"] = {
        "status": "completed",
        "model": "gpt-5.6-terra",
        "model_calls": len(ordered_terra),
        "shared_artifact": "terra_rule_mapping",
        "metrics": terra_metrics,
    }
    comparisons["gpt_5_6_hypothesis_mapping_without_compiler"] = {
        "status": "completed",
        "model": "gpt-5.6-terra",
        "shared_artifact": "terra_rule_mapping",
        "compiler_used": False,
        **_registry_metrics(ordered_terra),
        "metrics": terra_metrics,
    }
    comparisons["gpt_5_6_plus_compiler_without_learner_response"] = {
        "status": "completed",
        "model": "gpt-5.6-terra",
        "shared_artifact": "terra_rule_mapping",
        "compiler_used": True,
        "separating_probe_rate": _rate(separating, len(parsed_records)),
        "deterministic_reproduction_rate": _rate(reproduced, len(parsed_records)),
        "abstention_rate": _rate(len(parsed_records) - separating, len(parsed_records)),
        "learner_responses_collected": 0,
        "metrics": terra_metrics,
    }

    item_rows: list[dict[str, object]] = []
    for item in terra_items:
        terra = terra_results[item.manifest_id]
        sol = sol_results[item.manifest_id]
        tier = next(
            cast("str", record["tier"])
            for record in records
            if record["manifest_id"] == item.manifest_id
        )
        item_rows.append(
            {
                "manifest_id": item.manifest_id,
                "tier": tier,
                "expected_template_ids": list(item.expected),
                "terra": {
                    "status": "completed" if terra.mapping is not None else "abstained",
                    "predicted_template_ids": list(item.predicted or ()),
                    "response_id": terra.response_id,
                    "request_id": terra.request_id,
                    "prompt_hash": terra.prompt_hash,
                    "failure": terra.failure,
                },
                "sol": {
                    "status": "completed" if sol.mapping is not None else "abstained",
                    "predicted_template_ids": (
                        [hypothesis.template_id for hypothesis in sol.mapping.hypotheses]
                        if sol.mapping is not None
                        else []
                    ),
                    "response_id": sol.response_id,
                    "request_id": sol.request_id,
                    "prompt_hash": sol.prompt_hash,
                    "failure": sol.failure,
                },
                "terra_probe_specification_hash": compiled_hashes[item.manifest_id],
            }
        )

    total_cost = sum((result.cost_usd for result in model_results), start=Decimal())
    latencies = [result.latency_ms for result in model_results]
    report.update(
        {
            "generated_at": generated_at,
            "protocol_sha256": protocol_sha256,
            "model_calls_made": len(model_results),
            "model_results_status": "completed",
            "model_comparison": {
                "terra": {
                    **_registry_metrics(ordered_terra),
                    "metrics": terra_metrics,
                },
                "sol": {
                    **_registry_metrics(ordered_sol),
                    "metrics": sol_metrics,
                },
            },
            "telemetry": {
                "total_cost_usd": f"{total_cost:.6f}",
                "latency_ms": {
                    "p50": _nearest_rank_percentile(latencies, 0.50),
                    "p95": _nearest_rank_percentile(latencies, 0.95),
                    "p99": _nearest_rank_percentile(latencies, 0.99),
                },
                "calls": [
                    {
                        "manifest_id": result.manifest_id,
                        "purpose": result.purpose,
                        "requested_model_id": result.requested_model_id,
                        "returned_model_id": result.returned_model_id,
                        "response_id": result.response_id,
                        "request_id": result.request_id,
                        "latency_ms": result.latency_ms,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "reasoning_tokens": result.reasoning_tokens,
                        "cached_input_tokens": result.cached_input_tokens,
                        "cache_write_input_tokens": result.cache_write_input_tokens,
                        "cost_usd": f"{result.cost_usd:.6f}",
                        "prompt_hash": result.prompt_hash,
                        "prompt_cache_key": result.prompt_cache_key,
                        "schema_valid": result.schema_valid,
                        "failure": result.failure,
                    }
                    for result in model_results
                ],
            },
            "items": item_rows,
        }
    )
    return report


def _benchmark_case(record: Mapping[str, object]) -> CreateCaseRequest:
    runtime_input = record.get("runtime_input")
    if not isinstance(runtime_input, Mapping):
        msg = "benchmark record requires runtime_input"
        raise TypeError(msg)
    return CreateCaseRequest.model_validate(
        {
            "source_tier": runtime_input.get("source_tier"),
            "problem": runtime_input.get("problem"),
            "observed_work": runtime_input.get("observed_work"),
            "deidentified_attestation": False,
        }
    )


def _mapping_from_output(
    output_text: str | None,
    *,
    purpose: Literal["terra", "sol"],
    case: CreateCaseRequest,
) -> tuple[RuleMappingV1 | None, str | None]:
    if output_text is None:
        return None, "malformed_output"
    text_format: type[BaseModel] = TerraAnalysisV1 if purpose == "terra" else RuleMappingV1
    try:
        parsed = text_format.model_validate_json(output_text)
    except ValueError:
        return None, "malformed_output"
    mapping = (
        parsed.mapping
        if isinstance(parsed, TerraAnalysisV1)
        else cast("RuleMappingV1", parsed)
    )
    allowed = allowed_evidence_refs(case)
    if not all(
        set(hypothesis.evidence_refs).issubset(allowed)
        for hypothesis in mapping.hypotheses
    ):
        return None, "invalid_evidence_refs"
    return mapping, None


async def _call_model_once(
    *,
    client: BenchmarkResponsesClient,
    record: Mapping[str, object],
    purpose: Literal["terra", "sol"],
    monotonic: Callable[[], float],
) -> BenchmarkModelResult:
    manifest_id, _question_id, _expected = _record_fields(record)
    case = _benchmark_case(record)
    prompt = build_prompt(case, purpose=purpose)
    text_format: type[BaseModel] = TerraAnalysisV1 if purpose == "terra" else RuleMappingV1
    requested_model = MODEL_IDS[purpose]
    client_request_id = hashlib.sha256(
        f"cognisect-benchmark.v1:{manifest_id}:{purpose}".encode()
    ).hexdigest()
    started = monotonic()
    response = await client.responses.create(
        model=requested_model,
        instructions=prompt.instructions,
        input=prompt.input_text,
        text={
            "format": {
                "type": "json_schema",
                "name": response_schema_name(text_format),
                "schema": provider_json_schema(text_format),
                "strict": True,
            }
        },
        prompt_cache_key=prompt.prompt_cache_key,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
        store=False,
        metadata={"evaluation": "cognisect.evaluation-protocol.v1", "purpose": purpose},
        extra_headers={"X-Client-Request-Id": client_request_id},
    )
    latency_ms = max(0, round((monotonic() - started) * 1_000))
    returned_model_value = getattr(response, "model", None)
    response_id_value = getattr(response, "id", None)
    request_id_value = getattr(response, "_request_id", None)
    returned_model = (
        returned_model_value
        if isinstance(returned_model_value, str) and returned_model_value
        else None
    )
    response_id = (
        response_id_value
        if isinstance(response_id_value, str) and response_id_value
        else None
    )
    request_id = (
        request_id_value
        if isinstance(request_id_value, str) and request_id_value
        else None
    )
    usage_valid = True
    try:
        usage = usage_from_response(response)
        cost = calculate_cost_usd(requested_model, usage)
    except (AttributeError, OverflowError, TypeError, ValueError):
        usage_valid = False
        usage = TokenUsage(input_tokens=0, output_tokens=0)
        cost = Decimal()
    identity_valid = (
        response_id is not None
        and returned_model is not None
        and returned_model_is_allowed(requested_model, returned_model)
        and (request_id_value is None or request_id is not None)
        and request_id != response_id
    )
    mapping: RuleMappingV1 | None
    failure: str | None
    if not usage_valid or not identity_valid:
        mapping = None
        failure = "policy_failure"
    elif response_is_refusal(response):
        mapping = None
        failure = "refusal"
    else:
        mapping, failure = _mapping_from_output(
            single_output_text(response), purpose=purpose, case=case
        )
    return BenchmarkModelResult(
        manifest_id=manifest_id,
        purpose=purpose,
        mapping=mapping,
        schema_valid=mapping is not None,
        requested_model_id=requested_model,
        returned_model_id=returned_model,
        response_id=response_id,
        request_id=request_id,
        latency_ms=latency_ms,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_input_tokens=usage.cache_write_input_tokens,
        cost_usd=cost,
        prompt_hash=prompt.full_prompt_sha256,
        prompt_cache_key=prompt.prompt_cache_key,
        failure=failure,
    )


async def run_live_model_calls(
    manifest: Mapping[str, object],
    *,
    client: BenchmarkResponsesClient,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[BenchmarkModelResult]:
    """Run exactly one Terra and one Sol call per frozen record, without repair."""
    raw_records = manifest.get("records")
    if not isinstance(raw_records, list) or not all(
        isinstance(record, Mapping) for record in raw_records
    ):
        msg = "evaluation manifest records must be objects"
        raise TypeError(msg)
    records = cast("list[Mapping[str, object]]", raw_records)
    results: list[BenchmarkModelResult] = []
    for record in records:
        results.extend(
            [
                await _call_model_once(
                    client=client,
                    record=record,
                    purpose=purpose,
                    monotonic=monotonic,
                )
                for purpose in ("terra", "sol")
            ]
        )
    return results
