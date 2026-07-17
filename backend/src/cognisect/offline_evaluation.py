"""Claim-limited deterministic evaluation for public educator-authored fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cognisect.compiler import CompiledProbe, compile_probe, reproduce_probe_hash
from cognisect.interpreter import accept_hypotheses
from cognisect.models import RuleInstanceV1, RuleMappingV1, TemplateId
from cognisect.provenance import validate_evaluation_manifest, validate_provenance_ledger

_DESCRIPTIONS: dict[TemplateId, str] = {
    "add_subtrahend": "Treats the written subtraction as addition.",
    "ignore_subtrahend_sign": "Uses the second integer's magnitude regardless of its sign.",
    "absolute_difference": "Reports the non-negative difference between magnitudes.",
    "subtract_magnitudes": "Removes signs and retains written subtraction order.",
    "keep_minuend_sign": "Applies the first integer's sign to the magnitude difference.",
    "negative_magnitude_sum": "Adds magnitudes and reports a negative result.",
}
MIN_DISTINCT_PREDICTIONS = 2


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        msg = f"{path} must contain a JSON object"
        raise TypeError(msg)
    return value


def _mapping(template_ids: list[TemplateId]) -> RuleMappingV1:
    return RuleMappingV1(
        schema_version="rule_mapping.v1",
        hypotheses=[
            RuleInstanceV1(
                template_id=template_id,
                evidence_refs=["observed_work.full"],
                description=_DESCRIPTIONS[template_id],
                rank=index,
            )
            for index, template_id in enumerate(template_ids, start=1)
        ],
    )


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6)


def run_public_fixture_evaluation(
    ledger_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Run only the deterministic compiler on frozen, publicly cleared fixtures."""
    ledger = _load_json(ledger_path)
    manifest = _load_json(manifest_path)
    provenance_records = validate_provenance_ledger(ledger)
    summary = validate_evaluation_manifest(manifest, provenance_records=provenance_records)

    accepted_items = 0
    unique_rules = 0
    requested_rules = 0
    separating_items = 0
    reproduced_items = 0
    abstained_items = 0
    tier_counts: dict[str, int] = {}
    item_results: list[dict[str, Any]] = []
    for item in manifest["records"]:
        runtime_input = item["runtime_input"]
        template_ids = item["evaluation_only"]["expected_template_ids"]
        mapping = _mapping(template_ids)
        accepted = accept_hypotheses(mapping)
        requested_rules += len(mapping.hypotheses)
        unique_rules += len(accepted)
        if len(accepted) == len(mapping.hypotheses):
            accepted_items += 1
        problem = runtime_input["problem"]
        result = compile_probe(mapping, problem["a"], problem["b"])
        tier = runtime_input["source_tier"]
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if not isinstance(result, CompiledProbe):
            abstained_items += 1
            item_results.append(
                {
                    "manifest_id": item["manifest_id"],
                    "tier": tier,
                    "status": "abstained",
                    "reason": result.reason,
                    "probe_specification_hash": None,
                }
            )
            continue
        predictions = {hypothesis.prediction for hypothesis in result.hypotheses}
        if len(predictions) >= MIN_DISTINCT_PREDICTIONS:
            separating_items += 1
        if reproduce_probe_hash(result) == result.specification_hash:
            reproduced_items += 1
        item_results.append(
            {
                "manifest_id": item["manifest_id"],
                "tier": tier,
                "status": "compiled",
                "chosen_problem": {"a": result.chosen_problem.a, "b": result.chosen_problem.b},
                "distinct_predictions": len(predictions),
                "probe_specification_hash": result.specification_hash,
            }
        )

    count = summary.record_count
    return {
        "schema_version": "cognisect.evaluation-report.v1",
        "evaluation_kind": "deterministic_fixture_harness",
        "manifest_schema_version": manifest["schema_version"],
        "manifest_frozen_at": manifest["frozen_at"],
        "model_calls_made": 0,
        "learner_responses_collected": 0,
        "record_count": count,
        "tiers": dict(sorted(tier_counts.items())),
        "metrics": {
            "registry_acceptance_rate": _rate(accepted_items, count),
            "unique_semantic_rule_rate": _rate(unique_rules, requested_rules),
            "separating_probe_rate": _rate(separating_items, count),
            "deterministic_reproduction_rate": _rate(reproduced_items, count),
            "abstention_rate": _rate(abstained_items, count),
        },
        "item_results": item_results,
        "claim_scope": manifest["claim_scope"],
    }
