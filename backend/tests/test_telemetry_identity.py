"""Provider response and request identity truth-preservation contracts."""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cognisect import model_policy
from cognisect.config import Settings
from cognisect.model_analyzer import ResponsesAnalyzer
from cognisect.model_policy import InstructionalNotePlanV1, TerraAnalysisV1
from cognisect.models import RuleInstanceV1, RuleMappingV1
from cognisect.services import AnalysisInput


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        abuse_key_pepper="a" * 32,
        proxy_signing_secret="p" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="sk-test-" + ("k" * 32),
    )


def _analysis_input() -> AnalysisInput:
    return AnalysisInput(
        case_id=uuid4(),
        workflow_id=uuid4(),
        source_tier="educator_authored",
        original_a=-3,
        original_b=5,
        observed_work="-3 - 5 = 2",
    )


def _terra_payload() -> TerraAnalysisV1:
    return TerraAnalysisV1(
        schema_version="terra_analysis.v1",
        mapping=RuleMappingV1(
            schema_version="rule_mapping.v1",
            hypotheses=[
                RuleInstanceV1(
                    template_id="add_subtrahend",
                    evidence_refs=["observed_work"],
                    description="Adds the written second operand.",
                    rank=1,
                ),
                RuleInstanceV1(
                    template_id="absolute_difference",
                    evidence_refs=["observed_work"],
                    description="Uses the non-negative magnitude difference.",
                    rank=2,
                ),
            ],
        ),
        instructional_note_plan=InstructionalNotePlanV1(
            schema_version="instructional_note_plan.v1",
            observation="multiple_hypotheses_fit_observed_work",
            teacher_action="review_compiled_probe",
        ),
    )


def _response(
    *,
    response_id: object = "resp-provider-123",
    request_id: object = "req-provider-456",
    returned_model: str = "gpt-5.6-terra",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        _request_id=request_id,
        model=returned_model,
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        text=_terra_payload().model_dump_json(),
                    )
                ],
            )
        ],
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            input_tokens_details=SimpleNamespace(cached_tokens=25, cache_write_tokens=10),
            output_tokens_details=SimpleNamespace(reasoning_tokens=7),
        ),
    )


class _Responses:
    def __init__(self, *responses: SimpleNamespace) -> None:
        self._responses = deque(responses)

    async def create(self, **_kwargs: object) -> SimpleNamespace:
        return self._responses.popleft()


def _client(*responses: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(responses=_Responses(*responses))


def test_returned_model_policy_allows_only_exact_or_requested_snapshot() -> None:
    assert model_policy.returned_model_is_allowed("gpt-5.6-terra", "gpt-5.6-terra")
    assert model_policy.returned_model_is_allowed(
        "gpt-5.6-terra", "gpt-5.6-terra-2026-07-16"
    )
    assert not model_policy.returned_model_is_allowed("gpt-5.6-terra", "gpt-5.6-sol")
    assert not model_policy.returned_model_is_allowed("gpt-5.6-terra", "")


@pytest.mark.asyncio
async def test_analyzer_preserves_distinct_response_and_provider_request_ids() -> None:
    result = await ResponsesAnalyzer(
        _settings(), client=_client(_response())
    ).analyze(_analysis_input())

    assert result.mapping is not None
    assert result.response_id == "resp-provider-123"
    assert result.request_id == "req-provider-456"
    assert result.model_calls[0].response_id == "resp-provider-123"
    assert result.model_calls[0].request_id == "req-provider-456"


@pytest.mark.asyncio
async def test_missing_provider_request_id_remains_none() -> None:
    result = await ResponsesAnalyzer(
        _settings(), client=_client(_response(request_id=None))
    ).analyze(_analysis_input())

    assert result.mapping is not None
    assert result.response_id == "resp-provider-123"
    assert result.request_id is None
    assert result.model_calls[0].request_id is None
    assert result.model_calls[0].request_id != "None"


@pytest.mark.asyncio
async def test_missing_response_id_fails_closed_without_artifact() -> None:
    result = await ResponsesAnalyzer(
        _settings(), client=_client(_response(response_id=""))
    ).analyze(_analysis_input())

    assert result.mapping is None
    assert result.abstention_cause == "policy_failure"
    assert result.response_id is None
    assert result.model_calls[0].status == "policy_failure"


@pytest.mark.asyncio
async def test_disallowed_returned_model_keeps_valid_incurred_usage_and_cost() -> None:
    result = await ResponsesAnalyzer(
        _settings(), client=_client(_response(returned_model="gpt-5.6-sol"))
    ).analyze(_analysis_input())

    assert result.mapping is None
    assert result.abstention_cause == "policy_failure"
    telemetry = result.model_calls[0]
    assert telemetry.status == "policy_failure"
    assert telemetry.response_id == "resp-provider-123"
    assert telemetry.request_id == "req-provider-456"
    assert telemetry.input_tokens == 100
    assert telemetry.output_tokens == 20
    assert telemetry.cost_usd == Decimal("0.000500")


@pytest.mark.asyncio
async def test_malformed_usage_never_string_coerces_non_string_identity_metadata() -> None:
    response = _response(response_id=123, request_id=456)
    response.usage.input_tokens = "not-an-integer"

    result = await ResponsesAnalyzer(
        _settings(), client=_client(response)
    ).analyze(_analysis_input())

    assert result.mapping is None
    assert result.abstention_cause == "policy_failure"
    assert result.response_id is None
    assert result.request_id is None
    assert result.model_calls[0].response_id is None
    assert result.model_calls[0].request_id is None


def test_shared_identity_invariant_rejects_non_string_provider_request_metadata() -> None:
    assert not model_policy.provider_telemetry_identity_is_valid(
        expected_requested_model_id="gpt-5.6-terra",
        reported_requested_model_id="gpt-5.6-terra",
        returned_model_id="gpt-5.6-terra",
        response_id="resp-provider-123",
        request_id=123,
    )


@pytest.mark.asyncio
async def test_valid_usage_with_non_string_provider_request_id_fails_closed() -> None:
    result = await ResponsesAnalyzer(
        _settings(), client=_client(_response(request_id=123))
    ).analyze(_analysis_input())

    assert result.mapping is None
    assert result.abstention_cause == "policy_failure"
    assert result.response_id == "resp-provider-123"
    assert result.request_id is None
    assert result.model_calls[0].status == "policy_failure"


@pytest.mark.asyncio
async def test_equal_response_and_request_ids_fail_closed_as_conflated() -> None:
    result = await ResponsesAnalyzer(
        _settings(),
        client=_client(_response(response_id="provider-same", request_id="provider-same")),
    ).analyze(_analysis_input())

    assert result.mapping is None
    assert result.abstention_cause == "policy_failure"
    assert result.model_calls[0].status == "policy_failure"
