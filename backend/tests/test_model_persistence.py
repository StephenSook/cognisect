"""Production analyzer wiring and model telemetry persistence contracts."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, select

import cognisect.api as api_module
from cognisect.api_models import CreateCaseRequest
from cognisect.config import Settings
from cognisect.database import create_session_factory
from cognisect.db_models import ModelCallRecord
from cognisect.model_analyzer import ResponsesAnalyzer
from cognisect.services import (
    AnalysisInput,
    AnalyzerResult,
    ModelCallTelemetry,
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
    async def parse(self, **_kwargs):
        raise AssertionError("cost preflight must prevent the provider request")


class ForbiddenClient:
    responses = ForbiddenResponses()


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
