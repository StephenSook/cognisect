"""Bounded official Responses API analyzer with typed non-release outcomes."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol, TypeVar, cast

from openai import APITimeoutError, AsyncOpenAI
from pydantic import BaseModel

from cognisect.api_models import CreateCaseRequest
from cognisect.config import Settings
from cognisect.interpreter import accept_hypotheses
from cognisect.model_policy import (
    LONG_CONTEXT_THRESHOLD_TOKENS,
    MIN_SEPARATING_ALTERNATIVES,
    MODEL_IDS,
    ROUTE_VERSION,
    NormalizedEvidenceV1,
    TokenUsage,
    calculate_cost_usd,
    initial_route,
    route_review_flags,
    should_use_sol,
)
from cognisect.models import RuleMappingV1
from cognisect.prompts.analysis_v1 import (
    PromptEnvelope,
    allowed_evidence_refs,
    build_prompt,
)
from cognisect.services import (
    AnalysisInput,
    AnalyzerAbstentionCause,
    AnalyzerResult,
    ModelCallTelemetry,
)

_MAX_OUTPUT_TOKENS = 1_200
_Purpose = Literal["luna", "terra", "sol"]
_T = TypeVar("_T", bound=BaseModel)


class _ParsedResponse(Protocol):
    id: str
    model: str
    output: object
    usage: object
    output_parsed: object


class _ResponsesResource(Protocol):
    async def parse(self, **kwargs: object) -> _ParsedResponse: ...


class _ResponsesClient(Protocol):
    responses: _ResponsesResource


@dataclass(frozen=True, slots=True)
class _CallResult:
    parsed: BaseModel | None
    telemetry: ModelCallTelemetry | None
    cause: AnalyzerAbstentionCause | None


def _is_refusal(response: object) -> bool:
    for item in getattr(response, "output", ()):
        if getattr(item, "type", None) != "message":
            continue
        if any(getattr(content, "type", None) == "refusal" for content in item.content):
            return True
    return False


def _usage_from_response(response: object) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage(input_tokens=0, output_tokens=0)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return TokenUsage(
        input_tokens=int(usage.input_tokens),
        output_tokens=int(usage.output_tokens),
        reasoning_tokens=int(getattr(output_details, "reasoning_tokens", 0) or 0),
        cached_input_tokens=int(getattr(input_details, "cached_tokens", 0) or 0),
        cache_write_input_tokens=int(getattr(input_details, "cache_write_tokens", 0) or 0),
    )


def _as_case_request(case: AnalysisInput, *, observed_work: str | None = None) -> CreateCaseRequest:
    return CreateCaseRequest.model_validate(
        {
            "source_tier": case.source_tier,
            "problem": {"a": case.original_a, "b": case.original_b},
            "observed_work": observed_work if observed_work is not None else case.observed_work,
            "deidentified_attestation": case.source_tier == "custom",
        }
    )


class ResponsesAnalyzer:
    """Route bounded structured calls and never expose provider exceptions or content."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: _ResponsesClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize with frozen settings and an optional official client."""
        self._settings = settings
        self._client: _ResponsesClient = client or cast(
            "_ResponsesClient",
            AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value()),
        )
        self._monotonic = monotonic

    def _models_are_frozen(self) -> bool:
        return (
            self._settings.model_luna == MODEL_IDS["luna"]
            and self._settings.model_terra == MODEL_IDS["terra"]
            and self._settings.model_sol == MODEL_IDS["sol"]
        )

    def _projected_cost(self, purpose: _Purpose, prompt: PromptEnvelope) -> Decimal:
        # Counting every UTF-8 character as a token is deliberately conservative and
        # also proves these bounded prompts stay below the long-context price tier.
        estimated_input = len(prompt.instructions) + len(prompt.input_text)
        if estimated_input > LONG_CONTEXT_THRESHOLD_TOKENS:
            return Decimal("Infinity")
        return calculate_cost_usd(
            MODEL_IDS[purpose],
            TokenUsage(
                input_tokens=estimated_input,
                output_tokens=_MAX_OUTPUT_TOKENS,
            ),
        )

    @staticmethod
    def _empty_telemetry(
        *,
        requested_model: str,
        prompt: PromptEnvelope,
        status: str,
        latency_ms: int,
    ) -> ModelCallTelemetry:
        """Record a content-free attempted or preflight-blocked call accurately."""
        return ModelCallTelemetry(
            requested_model_id=requested_model,
            returned_model_id=None,
            request_id=None,
            status=status,
            latency_ms=latency_ms,
            input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            cost_usd=Decimal(),
            prompt_hash=prompt.full_prompt_sha256,
            route_version=ROUTE_VERSION,
            prompt_cache_key=prompt.prompt_cache_key,
        )

    async def _call(
        self,
        *,
        purpose: _Purpose,
        prompt_case: CreateCaseRequest,
        text_format: type[_T],
        repair: bool,
        spent: Decimal,
    ) -> _CallResult:
        prompt = build_prompt(prompt_case, purpose=purpose, repair=repair)
        requested_model = MODEL_IDS[purpose]
        maximum = Decimal(str(self._settings.max_model_cost_usd))
        if spent + self._projected_cost(purpose, prompt) > maximum:
            return _CallResult(
                parsed=None,
                telemetry=self._empty_telemetry(
                    requested_model=requested_model,
                    prompt=prompt,
                    status="cost_blocked",
                    latency_ms=0,
                ),
                cause="cost_limit",
            )

        started = self._monotonic()
        try:
            response = await self._client.responses.parse(
                model=requested_model,
                instructions=prompt.instructions,
                input=prompt.input_text,
                text_format=text_format,
                prompt_cache_key=prompt.prompt_cache_key,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                store=False,
                metadata={"repair": "1", "route": ROUTE_VERSION}
                if repair
                else {"route": ROUTE_VERSION},
            )
        except (TimeoutError, APITimeoutError):
            latency_ms = max(0, round((self._monotonic() - started) * 1_000))
            return _CallResult(
                parsed=None,
                telemetry=self._empty_telemetry(
                    requested_model=requested_model,
                    prompt=prompt,
                    status="timeout",
                    latency_ms=latency_ms,
                ),
                cause="timeout",
            )
        except Exception:  # noqa: BLE001 - every provider/parser failure becomes typed.
            latency_ms = max(0, round((self._monotonic() - started) * 1_000))
            return _CallResult(
                parsed=None,
                telemetry=self._empty_telemetry(
                    requested_model=requested_model,
                    prompt=prompt,
                    status="policy_failure",
                    latency_ms=latency_ms,
                ),
                cause="policy_failure",
            )

        latency_ms = max(0, round((self._monotonic() - started) * 1_000))
        usage = _usage_from_response(response)
        returned_model = str(response.model)
        telemetry = ModelCallTelemetry(
            requested_model_id=requested_model,
            returned_model_id=returned_model,
            request_id=str(response.id),
            status="refused" if _is_refusal(response) else "completed",
            latency_ms=latency_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cache_write_input_tokens=usage.cache_write_input_tokens,
            cost_usd=calculate_cost_usd(requested_model, usage),
            prompt_hash=prompt.full_prompt_sha256,
            route_version=ROUTE_VERSION,
            prompt_cache_key=prompt.prompt_cache_key,
        )
        if _is_refusal(response):
            return _CallResult(parsed=None, telemetry=telemetry, cause="refusal")
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, text_format):
            return _CallResult(parsed=None, telemetry=telemetry, cause="malformed_output")
        return _CallResult(parsed=parsed, telemetry=telemetry, cause=None)

    @staticmethod
    def _result(
        *,
        mapping: RuleMappingV1 | None,
        cause: AnalyzerAbstentionCause | None,
        calls: list[ModelCallTelemetry],
        fallback_model: str,
    ) -> AnalyzerResult:
        final = calls[-1] if calls else None
        return AnalyzerResult(
            mapping=mapping,
            model_id=(final.returned_model_id or final.requested_model_id)
            if final is not None
            else fallback_model,
            model_snapshot=final.returned_model_id if final is not None else None,
            request_id=final.request_id if final is not None else None,
            model_calls=tuple(calls),
            abstention_cause=cause,
        )

    async def analyze(  # noqa: C901, PLR0911
        self, case: AnalysisInput
    ) -> AnalyzerResult:
        """Run at most three calls with one repair and a pre-call cost check."""
        calls: list[ModelCallTelemetry] = []
        if not self._models_are_frozen():
            return self._result(
                mapping=None,
                cause="policy_failure",
                calls=calls,
                fallback_model=self._settings.model_terra,
            )
        prompt_case = _as_case_request(case)
        purposes = initial_route(prompt_case)
        repair_used = False

        async def invoke(purpose: _Purpose, text_format: type[_T]) -> _CallResult:
            nonlocal repair_used

            def validate_references(result: _CallResult) -> _CallResult:
                if result.cause is not None or text_format is not RuleMappingV1:
                    return result
                mapping = cast("RuleMappingV1", result.parsed)
                allowed = allowed_evidence_refs(prompt_case)
                if all(
                    set(hypothesis.evidence_refs).issubset(allowed)
                    for hypothesis in mapping.hypotheses
                ):
                    return result
                return _CallResult(
                    parsed=None,
                    telemetry=result.telemetry,
                    cause="malformed_output",
                )

            result = await self._call(
                purpose=purpose,
                prompt_case=prompt_case,
                text_format=text_format,
                repair=False,
                spent=sum((item.cost_usd for item in calls), start=Decimal()),
            )
            result = validate_references(result)
            if result.telemetry is not None:
                calls.append(result.telemetry)
            if (
                result.cause == "malformed_output"
                and not repair_used
                and len(calls) < self._settings.max_model_calls_per_case
            ):
                repair_used = True
                result = await self._call(
                    purpose=purpose,
                    prompt_case=prompt_case,
                    text_format=text_format,
                    repair=True,
                    spent=sum((item.cost_usd for item in calls), start=Decimal()),
                )
                result = validate_references(result)
                if result.telemetry is not None:
                    calls.append(result.telemetry)
            return result

        terra_mapping: RuleMappingV1 | None = None
        for raw_purpose in purposes:
            purpose = cast("_Purpose", raw_purpose)
            if len(calls) >= self._settings.max_model_calls_per_case:
                return self._result(
                    mapping=None,
                    cause="cost_limit",
                    calls=calls,
                    fallback_model=MODEL_IDS[purpose],
                )
            text_format: type[BaseModel] = (
                NormalizedEvidenceV1 if purpose == "luna" else RuleMappingV1
            )
            result = await invoke(purpose, text_format)
            if result.cause is not None:
                return self._result(
                    mapping=None,
                    cause=result.cause,
                    calls=calls,
                    fallback_model=MODEL_IDS[purpose],
                )
            if purpose == "luna":
                normalized = cast("NormalizedEvidenceV1", result.parsed)
                prompt_case = _as_case_request(
                    case,
                    observed_work=normalized.model_dump_json(),
                )
            else:
                terra_mapping = cast("RuleMappingV1", result.parsed)

        if terra_mapping is None:
            return self._result(
                mapping=None,
                cause="policy_failure",
                calls=calls,
                fallback_model=MODEL_IDS["terra"],
            )
        accepted_count = len(accept_hypotheses(terra_mapping))
        review_flags = route_review_flags(_as_case_request(case))
        if should_use_sol(
            terra_completed=True,
            distinct_accepted_alternatives=accepted_count,
            ambiguity_flag=review_flags.ambiguity,
            adversarial_review_flag=review_flags.adversarial,
        ):
            if len(calls) >= self._settings.max_model_calls_per_case:
                return self._result(
                    mapping=None,
                    cause="no_separating_alternatives",
                    calls=calls,
                    fallback_model=MODEL_IDS["sol"],
                )
            sol_result = await invoke("sol", RuleMappingV1)
            if sol_result.cause is not None:
                return self._result(
                    mapping=None,
                    cause=sol_result.cause,
                    calls=calls,
                    fallback_model=MODEL_IDS["sol"],
                )
            terra_mapping = cast("RuleMappingV1", sol_result.parsed)

        if len(accept_hypotheses(terra_mapping)) < MIN_SEPARATING_ALTERNATIVES:
            return self._result(
                mapping=None,
                cause="no_separating_alternatives",
                calls=calls,
                fallback_model=MODEL_IDS["sol"],
            )
        return self._result(
            mapping=terra_mapping,
            cause=None,
            calls=calls,
            fallback_model=MODEL_IDS["terra"],
        )
