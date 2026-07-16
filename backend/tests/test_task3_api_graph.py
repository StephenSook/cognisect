"""Full Task 3 API loop with official Responses transport and real checkpoints."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx
import pytest
from asgi_lifespan import LifespanManager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from openai import AsyncOpenAI
from sqlalchemy import func, select, text

from cognisect.api import OWNER_COOKIE_NAME, create_app
from cognisect.config import Settings
from cognisect.database import create_session_factory
from cognisect.db_models import GeneratedProposalRecord, ModelCallRecord, WorkflowRecord
from cognisect.model_analyzer import ResponsesAnalyzer
from cognisect.workflow_graph import (
    WorkflowGraphRuntime,
    checkpoint_connection_url,
    secure_checkpoint_serializer,
)
from conftest import TEST_DATABASE_URL


@pytest.mark.postgres
async def test_production_lifespan_attaches_managed_runtime_without_implicit_setup(
    db_engine, db_session, monkeypatch
) -> None:
    del db_session

    async def forbidden_setup(_self):
        raise AssertionError("checkpoint setup belongs to the explicit release script")

    monkeypatch.setattr(AsyncPostgresSaver, "setup", forbidden_setup)
    settings = Settings(
        app_env="production",
        database_url=TEST_DATABASE_URL,
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        public_app_url="https://cognisect.example",
        openai_api_key="sk-test-" + ("k" * 32),
    )
    app = create_app(
        settings=settings,
        session_factory=create_session_factory(db_engine),
        analyzer=None,
    )
    assert app.state.graph_runtime is None

    async with LifespanManager(app):
        assert isinstance(app.state.graph_runtime, WorkflowGraphRuntime)


def _provider_response() -> dict[str, object]:
    mapping = {
        "schema_version": "rule_mapping.v1",
        "hypotheses": [
            {
                "template_id": "add_subtrahend",
                "evidence_refs": ["observed_work"],
                "description": "Adds the written second operand.",
                "rank": 1,
            },
            {
                "template_id": "absolute_difference",
                "evidence_refs": ["observed_work"],
                "description": "Uses a non-negative magnitude difference.",
                "rank": 2,
            },
        ],
    }
    return {
        "id": "resp_transport_terra",
        "created_at": 0,
        "model": "gpt-5.6-terra",
        "object": "response",
        "output": [
            {
                "id": "msg_transport_terra",
                "content": [
                    {
                        "annotations": [],
                        "text": json.dumps(mapping),
                        "type": "output_text",
                    }
                ],
                "role": "assistant",
                "status": "completed",
                "type": "message",
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": "completed",
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {
                "cache_write_tokens": 0,
                "cached_tokens": 0,
            },
            "output_tokens": 20,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 120,
        },
    }


@pytest.mark.postgres
async def test_full_api_loop_uses_official_transport_and_real_checkpoint_tables(
    db_engine, db_session
) -> None:
    del db_session
    provider_requests: list[dict[str, object]] = []

    async def provider_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        provider_requests.append(payload)
        assert payload["model"] == "gpt-5.6-terra"
        assert "reasoning" not in payload
        assert "include" not in payload
        return httpx.Response(200, json=_provider_response())

    settings = Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="sk-test-" + ("k" * 32),
    )
    sessions = create_session_factory(db_engine)
    provider_http = httpx.AsyncClient(
        transport=httpx.MockTransport(provider_handler),
        base_url="https://api.openai.test/v1",
    )
    async with (
        AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url="https://api.openai.test/v1",
            http_client=provider_http,
        ) as provider_client,
        AsyncPostgresSaver.from_conn_string(
            checkpoint_connection_url(TEST_DATABASE_URL),
            serde=secure_checkpoint_serializer(),
        ) as saver,
    ):
        await saver.setup()
        analyzer = ResponsesAnalyzer(settings, client=provider_client)
        app = create_app(
            settings=settings,
            session_factory=sessions,
            analyzer=analyzer,
        )
        service = app.state.workflow_service
        runtime = WorkflowGraphRuntime(
            sessions,
            saver,
            update_action=service.advance_response_update,
        )
        service.attach_graph_runtime(runtime)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            created = await client.post(
                "/v1/cases",
                headers={"Idempotency-Key": "task3-create"},
                json={
                    "source_tier": "educator_authored",
                    "problem": {"a": -3, "b": 5},
                    "observed_work": "-3 - 5 = 2",
                    "deidentified_attestation": False,
                },
            )
            identifiers = created.json()
            analyzed = await client.post(
                f"/v1/cases/{identifiers['case_id']}/analysis",
                headers={"Idempotency-Key": "task3-analysis"},
                json={"expected_version": 0},
            )
            approved = await client.post(
                f"/v1/workflows/{identifiers['workflow_id']}/probe-approval",
                headers={"Idempotency-Key": "task3-approval"},
                json={"expected_version": analyzed.json()["version"], "approved": True},
            )
            token = urlparse(approved.json()["response_url"]).path.rsplit("/", 1)[-1]
            submitted = await client.post(
                f"/v1/respond/{token}",
                headers={"Idempotency-Key": "task3-response"},
                json={"answer": 2},
            )
            pending = await client.get(f"/v1/workflows/{identifiers['workflow_id']}")
            reviewed = await client.post(
                f"/v1/workflows/{identifiers['workflow_id']}/review",
                headers={"Idempotency-Key": "task3-review"},
                json={
                    "expected_version": pending.json()["version"],
                    "decision": "approved",
                    "note": "reviewed",
                },
            )
            owner_secret = client.cookies[OWNER_COOKIE_NAME]

        assert created.status_code == 201
        assert analyzed.json()["state"] == "PROBE_READY"
        assert submitted.status_code == 200
        assert pending.json()["state"] == "AWAITING_REVIEW"
        assert reviewed.json()["state"] == "APPROVED"
        assert len(provider_requests) == 1

        async with sessions() as session:
            workflow = await session.get(WorkflowRecord, identifiers["workflow_id"])
            assert workflow is not None
            assert await session.scalar(select(func.count(ModelCallRecord.id))) == 1
            assert await session.scalar(select(func.count(GeneratedProposalRecord.id))) == 1
            checkpoint_count = await session.scalar(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
                {"thread_id": str(workflow.thread_id)},
            )
            assert checkpoint_count > 0

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            cookies={OWNER_COOKIE_NAME: owner_secret},
        ) as deletion_client:
            deleted = await deletion_client.delete(
                f"/v1/workflows/{identifiers['workflow_id']}",
                headers={"Idempotency-Key": "task3-delete"},
            )
        assert deleted.status_code == 204
        async with sessions() as session:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                remaining = await session.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE thread_id = :thread_id"),
                    {"thread_id": str(workflow.thread_id)},
                )
                assert remaining == 0
