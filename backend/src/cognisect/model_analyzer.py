"""Bounded official Responses API analyzer with typed non-release outcomes."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal, Protocol, TypeVar, cast

from openai import APITimeoutError, AsyncOpenAI
from pydantic import BaseModel

from cognisect.api_models import CreateCaseRequest
from cognisect.config import Settings
from cognisect.interpreter import accept_hypotheses
from cognisect.model_attempts import (
    AttemptJournal,
    ModelAttemptPlan,
    NullAttemptJournal,
)
from cognisect.model_policy import (
    LONG_CONTEXT_THRESHOLD_TOKENS,
    MIN_SEPARATING_ALTERNATIVES,
    MODEL_IDS,
    ROUTE_VERSION,
    NormalizedEvidenceV1,
    TerraAnalysisV1,
    TokenUsage,
    calculate_cost_usd,
    initial_route,
    provider_telemetry_identity_is_valid,
    render_instructional_note,
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
_UNSUPPORTED_PROVIDER_SCHEMA_KEYS = frozenset({"uniqueItems"})
_Purpose = Literal["luna", "terra", "sol"]
_T = TypeVar("_T", bound=BaseModel)


class _ParsedResponse(Protocol):
    id: str
    _request_id: str | None
    model: str
    output: object
    usage: object


class _ResponsesResource(Protocol):
    async def create(self, **kwargs: object) -> _ParsedResponse: ...


class _ResponsesClient(Protocol):
    responses: _ResponsesResource


@dataclass(frozen=True, slots=True)
class _CallResult:
    parsed: BaseModel | None
    telemetry: ModelCallTelemetry | None
    cause: AnalyzerAbstentionCause | None


def response_is_refusal(response: object) -> bool:
    """Return whether the provider response contains a refusal part."""
    for item in getattr(response, "output", ()):
        if getattr(item, "type", None) != "message":
            continue
        if any(getattr(content, "type", None) == "refusal" for content in item.content):
            return True
    return False


def single_output_text(response: object) -> str | None:
    """Return one assistant output text, rejecting missing or ambiguous output."""
    output_texts: list[str] = []
    for item in getattr(response, "output", ()):
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", ()):
            if getattr(content, "type", None) != "output_text":
                continue
            text = getattr(content, "text", None)
            if isinstance(text, str):
                output_texts.append(text)
    return output_texts[0] if len(output_texts) == 1 else None


def response_schema_name(text_format: type[BaseModel]) -> str:
    """Return the stable provider-facing schema name for a response contract."""
    names = {
        NormalizedEvidenceV1: "normalized_evidence_v1",
        TerraAnalysisV1: "terra_analysis_v1",
        RuleMappingV1: "rule_mapping_v1",
    }
    return names[text_format]


def provider_json_schema(text_format: type[BaseModel]) -> dict[str, object]:
    """Remove unsupported provider keywords without weakening runtime validation."""

    def sanitize(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: sanitize(nested)
                for key, nested in value.items()
                if key not in _UNSUPPORTED_PROVIDER_SCHEMA_KEYS
            }
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    return cast("dict[str, object]", sanitize(text_format.model_json_schema()))


def usage_from_response(response: object) -> TokenUsage:
    """Normalize provider usage metadata into the checked pricing contract."""
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
        journal: AttemptJournal | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize with frozen settings and an optional official client."""
        self._settings = settings
        self._client: _ResponsesClient = client or cast(
            "_ResponsesClient",
            AsyncOpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                max_retries=0,
                timeout=settings.model_timeout_seconds,
            ),
        )
        self._journal = journal or NullAttemptJournal()
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
            response_id=None,
        )

    async def _call(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
        self,
        *,
        case: AnalysisInput,
        attempt_ordinal: int,
        purpose: _Purpose,
        prompt_case: CreateCaseRequest,
        text_format: type[_T],
        repair: bool,
        spent: Decimal,
    ) -> _CallResult:
        prompt = build_prompt(prompt_case, purpose=purpose, repair=repair)
        requested_model = MODEL_IDS[purpose]
        plan = ModelAttemptPlan(
            case_id=case.case_id,
            workflow_id=case.workflow_id,
            attempt_ordinal=attempt_ordinal,
            purpose=purpose,
            repair=repair,
            requested_model_id=requested_model,
            prompt_hash=prompt.full_prompt_sha256,
            route_version=ROUTE_VERSION,
            prompt_cache_key=prompt.prompt_cache_key,
        )
        decision = await self._journal.plan(plan)
        if decision.action == "stale":
            return _CallResult(
                parsed=None,
                telemetry=decision.telemetry,
                cause="policy_failure",
            )
        if decision.action == "recovered":
            telemetry = decision.telemetry
            if telemetry is None:
                return _CallResult(parsed=None, telemetry=None, cause="policy_failure")
            causes: dict[str, AnalyzerAbstentionCause] = {
                "malformed_output": "malformed_output",
                "refused": "refusal",
                "timeout": "timeout",
                "policy_failure": "policy_failure",
                "cost_blocked": "cost_limit",
            }
            if telemetry.status != "completed":
                return _CallResult(
                    parsed=None,
                    telemetry=telemetry,
                    cause=causes.get(telemetry.status, "policy_failure"),
                )
            if not provider_telemetry_identity_is_valid(
                expected_requested_model_id=plan.requested_model_id,
                reported_requested_model_id=telemetry.requested_model_id,
                returned_model_id=telemetry.returned_model_id,
                response_id=telemetry.response_id,
                request_id=telemetry.request_id,
            ):
                return _CallResult(
                    parsed=None,
                    telemetry=replace(telemetry, status="policy_failure"),
                    cause="policy_failure",
                )
            try:
                parsed = (
                    decision.artifact
                    if isinstance(decision.artifact, text_format)
                    else text_format.model_validate(decision.artifact)
                )
            except ValueError:
                return _CallResult(
                    parsed=None,
                    telemetry=telemetry,
                    cause="policy_failure",
                )
            if not self._valid_artifact(
                parsed=parsed,
                text_format=text_format,
                case=case,
                prompt_case=prompt_case,
            ):
                return _CallResult(
                    parsed=None,
                    telemetry=telemetry,
                    cause="policy_failure",
                )
            return _CallResult(parsed=parsed, telemetry=telemetry, cause=None)

        maximum = Decimal(str(self._settings.max_model_cost_usd))
        if spent + self._projected_cost(purpose, prompt) > maximum:
            result = _CallResult(
                parsed=None,
                telemetry=self._empty_telemetry(
                    requested_model=requested_model,
                    prompt=prompt,
                    status="cost_blocked",
                    latency_ms=0,
                ),
                cause="cost_limit",
            )
            await self._journal.finalize(plan, cast("ModelCallTelemetry", result.telemetry), None)
            return result

        started = self._monotonic()
        try:
            response = await self._client.responses.create(
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
                metadata={"repair": "1", "route": ROUTE_VERSION}
                if repair
                else {"route": ROUTE_VERSION},
                extra_headers={"X-Client-Request-Id": decision.client_request_id},
            )
        except (TimeoutError, APITimeoutError):
            latency_ms = max(0, round((self._monotonic() - started) * 1_000))
            result = _CallResult(
                parsed=None,
                telemetry=self._empty_telemetry(
                    requested_model=requested_model,
                    prompt=prompt,
                    status="timeout",
                    latency_ms=latency_ms,
                ),
                cause="timeout",
            )
            await self._journal.finalize(plan, cast("ModelCallTelemetry", result.telemetry), None)
            return result
        except Exception:  # noqa: BLE001 - every provider/parser failure becomes typed.
            latency_ms = max(0, round((self._monotonic() - started) * 1_000))
            result = _CallResult(
                parsed=None,
                telemetry=self._empty_telemetry(
                    requested_model=requested_model,
                    prompt=prompt,
                    status="policy_failure",
                    latency_ms=latency_ms,
                ),
                cause="policy_failure",
            )
            await self._journal.finalize(plan, cast("ModelCallTelemetry", result.telemetry), None)
            return result

        latency_ms = max(0, round((self._monotonic() - started) * 1_000))
        provider_request_id = getattr(response, "_request_id", None)
        try:
            usage = usage_from_response(response)
        except Exception:  # noqa: BLE001 - malformed usage is a typed final outcome.
            telemetry = replace(
                self._empty_telemetry(
                    requested_model=requested_model,
                    prompt=prompt,
                    status="policy_failure",
                    latency_ms=latency_ms,
                ),
                returned_model_id=(
                    response.model
                    if isinstance(getattr(response, "model", None), str)
                    and response.model
                    else None
                ),
                response_id=(
                    response.id
                    if isinstance(getattr(response, "id", None), str)
                    and response.id
                    else None
                ),
                request_id=(
                    provider_request_id
                    if isinstance(provider_request_id, str) and provider_request_id
                    else None
                ),
            )
            await self._journal.finalize(plan, telemetry, None)
            return _CallResult(
                parsed=None,
                telemetry=telemetry,
                cause="policy_failure",
            )
        returned_model_value = getattr(response, "model", None)
        response_id_value = getattr(response, "id", None)
        request_id_value = provider_request_id
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
        try:
            cost_usd = calculate_cost_usd(requested_model, usage)
        except ValueError:
            telemetry = ModelCallTelemetry(
                requested_model_id=requested_model,
                returned_model_id=returned_model,
                request_id=request_id,
                status="policy_failure",
                latency_ms=latency_ms,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                cache_write_input_tokens=usage.cache_write_input_tokens,
                cost_usd=Decimal(),
                prompt_hash=prompt.full_prompt_sha256,
                route_version=ROUTE_VERSION,
                prompt_cache_key=prompt.prompt_cache_key,
                response_id=response_id,
            )
            await self._journal.finalize(plan, telemetry, None)
            return _CallResult(
                parsed=None,
                telemetry=telemetry,
                cause="policy_failure",
            )
        identity_is_valid = provider_telemetry_identity_is_valid(
            expected_requested_model_id=requested_model,
            reported_requested_model_id=requested_model,
            returned_model_id=returned_model,
            response_id=response_id,
            request_id=request_id_value,
        )
        telemetry = ModelCallTelemetry(
            requested_model_id=requested_model,
            returned_model_id=returned_model,
            request_id=request_id,
            status=(
                "refused"
                if identity_is_valid and response_is_refusal(response)
                else "completed" if identity_is_valid else "policy_failure"
            ),
            latency_ms=latency_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cache_write_input_tokens=usage.cache_write_input_tokens,
            cost_usd=cost_usd,
            prompt_hash=prompt.full_prompt_sha256,
            route_version=ROUTE_VERSION,
            prompt_cache_key=prompt.prompt_cache_key,
            response_id=response_id,
        )
        if not identity_is_valid:
            await self._journal.finalize(plan, telemetry, None)
            return _CallResult(parsed=None, telemetry=telemetry, cause="policy_failure")
        if response_is_refusal(response):
            result = _CallResult(parsed=None, telemetry=telemetry, cause="refusal")
            await self._journal.finalize(plan, telemetry, None)
            return result
        output_text = single_output_text(response)
        if output_text is None:
            malformed = replace(telemetry, status="malformed_output")
            result = _CallResult(
                parsed=None,
                telemetry=malformed,
                cause="malformed_output",
            )
            await self._journal.finalize(plan, malformed, None)
            return result
        try:
            parsed = text_format.model_validate_json(output_text)
        except ValueError:
            malformed = replace(telemetry, status="malformed_output")
            result = _CallResult(
                parsed=None,
                telemetry=malformed,
                cause="malformed_output",
            )
            await self._journal.finalize(plan, malformed, None)
            return result
        if not self._valid_artifact(
            parsed=parsed,
            text_format=text_format,
            case=case,
            prompt_case=prompt_case,
        ):
            malformed = replace(telemetry, status="malformed_output")
            result = _CallResult(
                parsed=None,
                telemetry=malformed,
                cause="malformed_output",
            )
            await self._journal.finalize(plan, malformed, None)
            return result
        await self._journal.finalize(plan, telemetry, parsed)
        return _CallResult(parsed=parsed, telemetry=telemetry, cause=None)

    @staticmethod
    def _valid_artifact(
        *,
        parsed: BaseModel,
        text_format: type[BaseModel],
        case: AnalysisInput,
        prompt_case: CreateCaseRequest,
    ) -> bool:
        if text_format is NormalizedEvidenceV1:
            normalized = cast("NormalizedEvidenceV1", parsed)
            return all(segment.text in case.observed_work for segment in normalized.segments)
        if text_format is TerraAnalysisV1:
            mapping = cast("TerraAnalysisV1", parsed).mapping
        elif text_format is RuleMappingV1:
            mapping = cast("RuleMappingV1", parsed)
        else:
            return False
        allowed = allowed_evidence_refs(prompt_case)
        return all(
            set(hypothesis.evidence_refs).issubset(allowed)
            for hypothesis in mapping.hypotheses
        )

    def _result(
        self,
        *,
        mapping: RuleMappingV1 | None,
        cause: AnalyzerAbstentionCause | None,
        calls: list[ModelCallTelemetry],
        fallback_model: str,
        proposal_draft: str | None = None,
    ) -> AnalyzerResult:
        final = calls[-1] if calls else None
        return AnalyzerResult(
            mapping=mapping,
            model_id=(final.returned_model_id or final.requested_model_id)
            if final is not None
            else fallback_model,
            model_snapshot=final.returned_model_id if final is not None else None,
            response_id=final.response_id if final is not None else None,
            request_id=final.request_id if final is not None else None,
            model_calls=tuple(calls),
            abstention_cause=cause,
            proposal_draft=proposal_draft,
            calls_persisted=self._journal.persists_attempts,
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

            result = await self._call(
                case=case,
                attempt_ordinal=len(calls) + 1,
                purpose=purpose,
                prompt_case=prompt_case,
                text_format=text_format,
                repair=False,
                spent=sum((item.cost_usd for item in calls), start=Decimal()),
            )
            if result.telemetry is not None:
                calls.append(result.telemetry)
            if (
                result.cause == "malformed_output"
                and not repair_used
                and len(calls) < self._settings.max_model_calls_per_case
            ):
                repair_used = True
                result = await self._call(
                    case=case,
                    attempt_ordinal=len(calls) + 1,
                    purpose=purpose,
                    prompt_case=prompt_case,
                    text_format=text_format,
                    repair=True,
                    spent=sum((item.cost_usd for item in calls), start=Decimal()),
                )
                if result.telemetry is not None:
                    calls.append(result.telemetry)
            return result

        terra_mapping: RuleMappingV1 | None = None
        terra_draft: str | None = None
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
                NormalizedEvidenceV1 if purpose == "luna" else TerraAnalysisV1
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
                terra_result = cast("TerraAnalysisV1", result.parsed)
                terra_mapping = terra_result.mapping
                terra_draft = render_instructional_note(
                    terra_result.instructional_note_plan
                )

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
                    proposal_draft=terra_draft,
                )
            sol_result = await invoke("sol", RuleMappingV1)
            if sol_result.cause is not None:
                return self._result(
                    mapping=None,
                    cause=sol_result.cause,
                    calls=calls,
                    fallback_model=MODEL_IDS["sol"],
                    proposal_draft=terra_draft,
                )
            terra_mapping = cast("RuleMappingV1", sol_result.parsed)

        if len(accept_hypotheses(terra_mapping)) < MIN_SEPARATING_ALTERNATIVES:
            return self._result(
                mapping=None,
                cause="no_separating_alternatives",
                calls=calls,
                fallback_model=MODEL_IDS["sol"],
                proposal_draft=terra_draft,
            )
        return self._result(
            mapping=terra_mapping,
            cause=None,
            calls=calls,
            fallback_model=MODEL_IDS["terra"],
            proposal_draft=terra_draft,
        )
