"""Production analyzer wiring and model telemetry persistence contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, inspect, select

import cognisect.api as api_module
from cognisect.api_models import CreateCaseRequest
from cognisect.config import Settings
from cognisect.database import create_session_factory
from cognisect.db_models import (
    AcceptedHypothesisRecord,
    AnalysisStepResultRecord,
    AuditEventRecord,
    CompiledProbeRecord,
    GeneratedProposalRecord,
    IdempotencyRecord,
    ModelCallRecord,
    ProbePredictionRecord,
    WorkflowRecord,
)
from cognisect.model_analyzer import ResponsesAnalyzer
from cognisect.model_attempts import PostgresAttemptJournal
from cognisect.model_policy import TerraAnalysisV1
from cognisect.models import RuleInstanceV1, RuleMappingV1
from cognisect.repositories import transition_workflow
from cognisect.services import (
    AnalysisInput,
    AnalyzerResult,
    ModelCallTelemetry,
    ReplayConflictError,
    WorkflowService,
)
from cognisect.workflow import WorkflowState


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        "owner_secret_pepper": "o" * 32,
        "learner_token_pepper": "l" * 32,
        "public_app_url": "https://cognisect.example",
        "openai_api_key": "sk-test-" + ("k" * 32),
    }
    return Settings(**{**values, **overrides})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_luna", "another-model"),
        ("model_terra", "another-model"),
        ("model_sol", "another-model"),
        ("langgraph_strict_msgpack", False),
    ],
)
def test_settings_reject_model_alias_drift_and_permissive_checkpoint_deserialization(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: value})


def test_build_app_installs_real_analyzer_when_production_settings_are_strict(monkeypatch) -> None:
    settings = _settings()
    monkeypatch.setattr(api_module, "Settings", lambda: settings)

    app = api_module.build_app()

    assert isinstance(app.state.workflow_service._analyzer, ResponsesAnalyzer)
    assert isinstance(app.state.workflow_service._analyzer._journal, PostgresAttemptJournal)


def test_model_call_record_has_complete_content_free_telemetry_columns() -> None:
    assert {
        "requested_model_id",
        "returned_model_id",
        "request_id",
        "status",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "cost_usd",
        "prompt_hash",
        "route_version",
        "prompt_cache_key",
    } <= set(inspect(ModelCallRecord).columns.keys())
    assert {
        "prompt",
        "response",
        "observed_work",
        "reasoning_text",
        "hidden_reasoning",
    }.isdisjoint(inspect(ModelCallRecord).columns.keys())


class RefusingAnalyzer:
    async def analyze(self, _case: AnalysisInput) -> AnalyzerResult:
        return AnalyzerResult(
            mapping=None,
            model_id="gpt-5.6-terra",
            model_snapshot="gpt-5.6-terra",
            request_id="resp_refused",
            abstention_cause="refusal",
            model_calls=(
                ModelCallTelemetry(
                    requested_model_id="gpt-5.6-terra",
                    returned_model_id="gpt-5.6-terra",
                    request_id="resp_refused",
                    status="refused",
                    latency_ms=17,
                    input_tokens=100,
                    output_tokens=2,
                    reasoning_tokens=0,
                    cached_input_tokens=50,
                    cache_write_input_tokens=0,
                    cost_usd=Decimal("0.000144"),
                    prompt_hash="a" * 64,
                    route_version="model_route.v1",
                    prompt_cache_key="cognisect.analysis_prompt.v1.terra",
                ),
            ),
        )


@pytest.mark.postgres
async def test_typed_model_abstention_persists_all_calls_and_abstains_not_fails(
    db_engine, db_session
) -> None:
    del db_session
    service = WorkflowService(
        create_session_factory(db_engine),
        _settings(app_env="test", public_app_url="http://localhost:3000"),
        analyzer=RefusingAnalyzer(),
    )
    created = await service.create_case(
        CreateCaseRequest(
            source_tier="custom",
            problem={"a": -3, "b": 5},
            observed_work="deidentified private evidence",
            deidentified_attestation=True,
        ),
        idempotency_key="typed-create",
    )

    workflow = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="typed-analysis",
    )

    assert workflow.state == WorkflowState.ABSTAINED
    factory = create_session_factory(db_engine)
    async with factory() as session:
        calls = list((await session.scalars(select(ModelCallRecord))).all())
    assert len(calls) == 1
    assert calls[0].requested_model_id == "gpt-5.6-terra"
    assert calls[0].returned_model_id == "gpt-5.6-terra"
    assert calls[0].reasoning_tokens == 0
    assert calls[0].prompt_hash == "a" * 64


class ForbiddenResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("cost preflight must prevent the provider request")


class ForbiddenClient:
    def __init__(self) -> None:
        self.responses = ForbiddenResponses()


class OneTerraResponses:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        mapping = RuleMappingV1(
            schema_version="rule_mapping.v1",
            hypotheses=[
                RuleInstanceV1(
                    template_id=template_id,
                    evidence_refs=["observed_work"],
                    description=f"Bounded alternative {rank}",
                    rank=rank,
                )
                for rank, template_id in enumerate(
                    ("add_subtrahend", "absolute_difference"), start=1
                )
            ],
        )
        output = TerraAnalysisV1(
            schema_version="terra_analysis.v1",
            mapping=mapping,
            instructional_note_draft="Two hypotheses remain; teacher review is required.",
        )
        return SimpleNamespace(
            id="resp_crash_gap",
            model="gpt-5.6-terra",
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text", text=output.model_dump_json())],
                )
            ],
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=20,
                input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=0),
                output_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )


class OneTerraClient:
    def __init__(self) -> None:
        self.responses = OneTerraResponses()


class BlockingRouteResponses(OneTerraResponses):
    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self.started = started
        self.release = release
        self.models: list[str] = []

    async def create(self, **kwargs):
        model = str(kwargs["model"])
        self.models.append(model)
        if model == "gpt-5.6-luna":
            self.calls += 1
            output_text = (
                '{"schema_version":"normalized_evidence.v1","segments":'
                '[{"ref":"observed_work","text":"deidentified evidence"}]}'
            )
            return SimpleNamespace(
                id="resp_concurrent_luna",
                model=model,
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", text=output_text)],
                    )
                ],
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=20,
                    input_tokens_details=SimpleNamespace(
                        cached_tokens=0, cache_write_tokens=0
                    ),
                    output_tokens_details=SimpleNamespace(reasoning_tokens=0),
                ),
            )
        self.started.set()
        await self.release.wait()
        return await super().create(**kwargs)


class BlockingRouteClient:
    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        self.responses = BlockingRouteResponses(started, release)


class PauseFirstCompletedAnalyzer:
    def __init__(
        self,
        analyzer: ResponsesAnalyzer,
        completed: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        self.analyzer = analyzer
        self.completed = completed
        self.release = release
        self.calls = 0

    async def analyze(self, case: AnalysisInput) -> AnalyzerResult:
        self.calls += 1
        result = await self.analyzer.analyze(case)
        if self.calls == 1:
            self.completed.set()
            await self.release.wait()
        return result


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("source_tier", "expected_provider_calls"),
    [("educator_authored", 1), ("custom", 2)],
)
async def test_concurrent_analysis_keys_cannot_hijack_active_route_or_duplicate_completion(
    db_engine,
    db_session,
    source_tier,
    expected_provider_calls,
) -> None:
    del db_session
    settings = _settings(app_env="test", public_app_url="http://localhost:3000")
    sessions = create_session_factory(db_engine)
    started = asyncio.Event()
    release = asyncio.Event()
    provider = BlockingRouteClient(started, release)
    service = WorkflowService(
        sessions,
        settings,
        analyzer=ResponsesAnalyzer(
            settings,
            client=provider,
            journal=PostgresAttemptJournal(sessions),
        ),
    )
    created = await service.create_case(
        CreateCaseRequest(
            source_tier=source_tier,
            problem={"a": -3, "b": 5},
            observed_work="deidentified evidence",
            deidentified_attestation=source_tier == "custom",
        ),
        idempotency_key=f"concurrent-{source_tier}-create",
    )
    first = asyncio.create_task(
        service.analyze_case(
            owner_secret=created.owner_secret,
            case_id=created.case_id,
            expected_version=0,
            idempotency_key="concurrent-original-analysis",
        )
    )
    await started.wait()

    with pytest.raises(ReplayConflictError):
        await service.analyze_case(
            owner_secret=created.owner_secret,
            case_id=created.case_id,
            expected_version=0,
            idempotency_key="concurrent-different-analysis",
        )
    with pytest.raises(ReplayConflictError):
        await service.analyze_case(
            owner_secret=created.owner_secret,
            case_id=created.case_id,
            expected_version=0,
            idempotency_key="concurrent-original-analysis",
        )
    during = await service.get_workflow(created.owner_secret, created.workflow_id)
    assert during.state == WorkflowState.ANALYZING
    assert not first.done()

    release.set()
    completed = await first
    replayed = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="concurrent-original-analysis",
    )

    assert completed.state == replayed.state == WorkflowState.PROBE_READY
    assert provider.responses.calls == expected_provider_calls
    async with sessions() as session:
        assert await session.scalar(select(func.count(ModelCallRecord.id))) == (
            expected_provider_calls
        )
        assert await session.scalar(select(func.count(AnalysisStepResultRecord.id))) == (
            expected_provider_calls
        )
        assert await session.scalar(select(func.count(AcceptedHypothesisRecord.id))) == 2
        assert await session.scalar(select(func.count(CompiledProbeRecord.id))) == 1
        assert await session.scalar(select(func.count(ProbePredictionRecord.id))) == 2
        assert await session.scalar(select(func.count(GeneratedProposalRecord.id))) == 1
        assert await session.scalar(select(func.count(IdempotencyRecord.id))) == 2
        assert await session.scalar(select(func.count(AuditEventRecord.id))) == 2


@pytest.mark.postgres
async def test_identical_recovery_after_finalized_attempt_serializes_one_aggregate(
    db_engine, db_session
) -> None:
    del db_session
    settings = _settings(app_env="test", public_app_url="http://localhost:3000")
    sessions = create_session_factory(db_engine)
    provider = OneTerraClient()
    finalized = asyncio.Event()
    release = asyncio.Event()
    analyzer = PauseFirstCompletedAnalyzer(
        ResponsesAnalyzer(
            settings,
            client=provider,
            journal=PostgresAttemptJournal(sessions),
        ),
        finalized,
        release,
    )
    service = WorkflowService(sessions, settings, analyzer=analyzer)
    created = await service.create_case(
        CreateCaseRequest(
            source_tier="educator_authored",
            problem={"a": -3, "b": 5},
            observed_work="deidentified evidence",
            deidentified_attestation=False,
        ),
        idempotency_key="completion-lock-create",
    )
    first = asyncio.create_task(
        service.analyze_case(
            owner_secret=created.owner_secret,
            case_id=created.case_id,
            expected_version=0,
            idempotency_key="completion-lock-analysis",
        )
    )
    await finalized.wait()
    second = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="completion-lock-analysis",
    )
    release.set()
    original = await first

    assert original.state == second.state == WorkflowState.PROBE_READY
    assert provider.responses.calls == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count(ModelCallRecord.id))) == 1
        assert await session.scalar(select(func.count(AnalysisStepResultRecord.id))) == 1
        assert await session.scalar(select(func.count(AcceptedHypothesisRecord.id))) == 2
        assert await session.scalar(select(func.count(CompiledProbeRecord.id))) == 1
        assert await session.scalar(select(func.count(ProbePredictionRecord.id))) == 2
        assert await session.scalar(select(func.count(GeneratedProposalRecord.id))) == 1
        assert await session.scalar(select(func.count(AuditEventRecord.id))) == 2


@pytest.mark.postgres
async def test_stale_planned_attempt_still_fails_closed_without_redispatch(
    db_engine, db_session
) -> None:
    del db_session
    settings = _settings(app_env="test", public_app_url="http://localhost:3000")
    sessions = create_session_factory(db_engine)
    started = asyncio.Event()
    release = asyncio.Event()
    provider = BlockingRouteClient(started, release)
    service = WorkflowService(
        sessions,
        settings,
        analyzer=ResponsesAnalyzer(
            settings,
            client=provider,
            journal=PostgresAttemptJournal(sessions),
        ),
    )
    created = await service.create_case(
        CreateCaseRequest(
            source_tier="educator_authored",
            problem={"a": -3, "b": 5},
            observed_work="deidentified evidence",
            deidentified_attestation=False,
        ),
        idempotency_key="stale-window-create",
    )
    original = asyncio.create_task(
        service.analyze_case(
            owner_secret=created.owner_secret,
            case_id=created.case_id,
            expected_version=0,
            idempotency_key="stale-window-analysis",
        )
    )
    await started.wait()
    async with sessions() as session, session.begin():
        planned = await session.scalar(select(ModelCallRecord))
        assert planned is not None
        planned.created_at = datetime.now(UTC) - timedelta(seconds=36)

    recovered = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="stale-window-analysis",
    )
    original.cancel()
    await asyncio.gather(original, return_exceptions=True)

    assert recovered.state == WorkflowState.ABSTAINED
    assert provider.responses.models == ["gpt-5.6-terra"]
    async with sessions() as session:
        assert await session.scalar(select(func.count(ModelCallRecord.id))) == 1
        assert await session.scalar(select(func.count(AnalysisStepResultRecord.id))) == 0
        assert await session.scalar(select(func.count(AuditEventRecord.id))) == 2


@pytest.mark.postgres
async def test_analysis_recovers_finalized_artifact_after_process_crash_without_redispatch(
    db_engine, db_session
) -> None:
    del db_session
    settings = _settings(app_env="test", public_app_url="http://localhost:3000")
    sessions = create_session_factory(db_engine)
    journal = PostgresAttemptJournal(sessions)
    provider = OneTerraClient()
    analyzer = ResponsesAnalyzer(settings, client=provider, journal=journal)
    service = WorkflowService(sessions, settings, analyzer=analyzer)
    created = await service.create_case(
        CreateCaseRequest(
            source_tier="educator_authored",
            problem={"a": -3, "b": 5},
            observed_work="deidentified evidence",
            deidentified_attestation=False,
        ),
        idempotency_key="crash-create",
    )
    async with sessions() as session, session.begin():
        workflow = await session.get(WorkflowRecord, created.workflow_id)
        assert workflow is not None
        await transition_workflow(
            session,
            workflow_id=workflow.id,
            owner_id=workflow.owner_id,
            expected_version=0,
            requested_state=WorkflowState.ANALYZING,
            event_key="crash-analysis:analysis-started",
        )
    discarded = await analyzer.analyze(
        AnalysisInput(
            case_id=created.case_id,
            workflow_id=created.workflow_id,
            source_tier="educator_authored",
            original_a=-3,
            original_b=5,
            observed_work="deidentified evidence",
        )
    )
    assert discarded.mapping is not None
    assert provider.responses.calls == 1

    recovered_provider = ForbiddenClient()
    recovered_service = WorkflowService(
        sessions,
        settings,
        analyzer=ResponsesAnalyzer(
            settings,
            client=recovered_provider,
            journal=PostgresAttemptJournal(sessions),
        ),
    )
    recovered = await recovered_service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="crash-analysis",
    )

    assert recovered.state == WorkflowState.PROBE_READY
    assert recovered_provider.responses.calls == []
    async with sessions() as session:
        assert await session.scalar(select(func.count(ModelCallRecord.id))) == 1
        assert await session.scalar(select(func.count(AnalysisStepResultRecord.id))) == 1

    async with sessions() as session, session.begin():
        call = await session.scalar(select(ModelCallRecord))
        assert call is not None
        call.prompt_hash = "b" * 64
    mismatch_provider = ForbiddenClient()
    mismatch = await ResponsesAnalyzer(
        settings,
        client=mismatch_provider,
        journal=PostgresAttemptJournal(sessions),
    ).analyze(
        AnalysisInput(
            case_id=created.case_id,
            workflow_id=created.workflow_id,
            source_tier="educator_authored",
            original_a=-3,
            original_b=5,
            observed_work="deidentified evidence",
        )
    )
    assert mismatch.abstention_cause == "policy_failure"
    assert mismatch_provider.responses.calls == []


@pytest.mark.postgres
async def test_task3_cost_preflight_persists_truthful_nonlegacy_telemetry(
    db_engine, db_session
) -> None:
    del db_session
    settings = _settings(
        app_env="test",
        public_app_url="http://localhost:3000",
        max_model_cost_usd=0.000001,
    )
    service = WorkflowService(
        create_session_factory(db_engine),
        settings,
        analyzer=ResponsesAnalyzer(settings, client=ForbiddenClient()),
    )
    created = await service.create_case(
        CreateCaseRequest(
            source_tier="educator_authored",
            problem={"a": -3, "b": 5},
            observed_work="deidentified evidence",
            deidentified_attestation=False,
        ),
        idempotency_key="preflight-create",
    )

    workflow = await service.analyze_case(
        owner_secret=created.owner_secret,
        case_id=created.case_id,
        expected_version=0,
        idempotency_key="preflight-analysis",
    )

    assert workflow.state == WorkflowState.ABSTAINED
    factory = create_session_factory(db_engine)
    async with factory() as session:
        call = await session.scalar(select(ModelCallRecord))
    assert call is not None
    assert call.status == "cost_blocked"
    assert call.request_id is None
    assert call.returned_model_id is None
    assert call.route_version == "model_route.v1"
    assert call.prompt_hash != "0" * 64
