"""Public FastAPI surface, cookie, ownership, and learner privacy contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
import pytest
from sqlalchemy import func, select, update

from cognisect.api import OWNER_COOKIE_NAME, create_app
from cognisect.config import Settings
from cognisect.database import create_session_factory
from cognisect.db_models import (
    CaseRecord,
    InvalidLearnerCommandRecord,
    LearnerResponseRecord,
    LearnerTokenRecord,
    OwnerRecord,
    WorkflowRecord,
)
from cognisect.models import RuleInstanceV1, RuleMappingV1
from cognisect.security import generate_secret, hash_secret
from cognisect.services import AnalysisInput, AnalyzerResult

EXPECTED_PATHS = {
    "/v1/cases",
    "/v1/cases/{case_id}/analysis",
    "/v1/workflows/{workflow_id}",
    "/v1/workflows/{workflow_id}/probe-approval",
    "/v1/respond/{token}",
    "/v1/workflows/{workflow_id}/review",
    "/v1/workflows/{workflow_id}/audit",
    "/health",
    "/version",
}


class ApiAnalyzer:
    async def analyze(self, _case: AnalysisInput) -> AnalyzerResult:
        return AnalyzerResult(
            mapping=RuleMappingV1(
                schema_version="rule_mapping.v1",
                hypotheses=[
                    RuleInstanceV1(
                        template_id="add_subtrahend",
                        evidence_refs=["segment-1"],
                        description="Adds the written second operand.",
                        rank=1,
                    ),
                    RuleInstanceV1(
                        template_id="absolute_difference",
                        evidence_refs=["segment-2"],
                        description="Uses a non-negative magnitude difference.",
                        rank=2,
                    ),
                ],
            ),
            model_id="test-model",
            model_snapshot="test-model-2026-07-16",
            request_id="req_test_metadata",
        )


@pytest.fixture
def api_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="",
    )


@pytest.fixture
def app(db_engine, db_session, api_settings):
    del db_session
    return create_app(
        settings=api_settings,
        session_factory=create_session_factory(db_engine),
        analyzer=ApiAnalyzer(),
    )


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as value:
        value.cookies.set(OWNER_COOKIE_NAME, generate_secret())
        yield value


def case_payload() -> dict[str, object]:
    return {
        "source_tier": "custom",
        "problem": {"a": -3, "b": 5},
        "observed_work": "-3 - 5 = 2",
        "deidentified_attestation": True,
    }


async def issue_learner_token(client: httpx.AsyncClient, suffix: str) -> str:
    """Create, analyze, and approve one probe through the public API."""
    created = await client.post(
        "/v1/cases",
        headers={"Idempotency-Key": f"{suffix}-create-key"},
        json=case_payload(),
    )
    identifiers = created.json()
    analyzed = await client.post(
        f"/v1/cases/{identifiers['case_id']}/analysis",
        headers={"Idempotency-Key": f"{suffix}-analysis-key"},
        json={"expected_version": 0},
    )
    approved = await client.post(
        f"/v1/workflows/{identifiers['workflow_id']}/probe-approval",
        headers={"Idempotency-Key": f"{suffix}-approval-key"},
        json={"expected_version": analyzed.json()["version"], "approved": True},
    )
    return urlparse(approved.json()["response_url"]).path.rsplit("/", 1)[-1]


@pytest.mark.postgres
async def test_public_route_paths_are_exact(app):
    assert set(app.openapi()["paths"]) == EXPECTED_PATHS
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


@pytest.mark.postgres
async def test_health_and_version(client):
    health = await client.get("/health")
    version = await client.get("/version")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert version.status_code == 200
    assert version.json()["registry_version"] == "rule_registry.v1"


@pytest.mark.postgres
async def test_mutation_requires_bounded_idempotency_header(client):
    missing = await client.post("/v1/cases", json=case_payload())
    too_short = await client.post(
        "/v1/cases", headers={"Idempotency-Key": "tiny"}, json=case_payload()
    )
    too_long = await client.post(
        "/v1/cases", headers={"Idempotency-Key": "x" * 201}, json=case_payload()
    )
    assert {missing.status_code, too_short.status_code, too_long.status_code} == {422}


@pytest.mark.postgres
async def test_custom_case_rejects_identifier_fields_at_http_boundary(client):
    payload = {**case_payload(), "learner_name": "Identifier must be rejected"}
    response = await client.post(
        "/v1/cases", headers={"Idempotency-Key": "reject-pii-key"}, json=payload
    )
    assert response.status_code == 422
    assert "Identifier must be rejected" not in response.text


@pytest.mark.postgres
async def test_full_http_loop_privacy_headers_and_audit(client, app):
    created = await client.post(
        "/v1/cases", headers={"Idempotency-Key": "create-case-key"}, json=case_payload()
    )
    assert created.status_code == 201
    assert OWNER_COOKIE_NAME in client.cookies
    identifiers = created.json()

    analyzed = await client.post(
        f"/v1/cases/{identifiers['case_id']}/analysis",
        headers={"Idempotency-Key": "analysis-key"},
        json={"expected_version": 0},
    )
    assert analyzed.status_code == 200
    teacher = analyzed.json()
    assert teacher["state"] == "PROBE_READY"
    assert {
        "schema_version",
        "registry_version",
        "prompt_version",
        "compiler_version",
        "model_snapshot",
        "model_request_id",
        "created_at",
        "updated_at",
        "version",
        "source_tier",
        "accepted_hypotheses",
        "compiled_probe",
        "deterministic_evidence",
        "review_result",
    }.issubset(teacher)
    assert teacher["source_tier"] == "custom"
    assert [item["rank"] for item in teacher["accepted_hypotheses"]] == [1, 2]
    assert teacher["compiled_probe"]["original_problem"] == {"a": -3, "b": 5}
    assert len(teacher["compiled_probe"]["specification_hash"]) == 64
    assert [item["rank"] for item in teacher["compiled_probe"]["predictions"]] == [1, 2]
    assert teacher["deterministic_evidence"] == []
    assert teacher["review_result"] is None

    approved = await client.post(
        f"/v1/workflows/{identifiers['workflow_id']}/probe-approval",
        headers={"Idempotency-Key": "probe-approval-key"},
        json={"expected_version": teacher["version"], "approved": True},
    )
    assert approved.status_code == 200
    response_url = approved.json()["response_url"]
    learner_path = urlparse(response_url).path
    assert learner_path == f"/respond/{learner_path.rsplit('/', 1)[-1]}"
    assert "/v1/respond/" not in response_url
    token = learner_path.rsplit("/", 1)[-1]

    learner_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )
    async with learner_client:
        probe = await learner_client.get(f"/v1/respond/{token}")
        assert probe.status_code == 200
        assert probe.headers["referrer-policy"] == "no-referrer"
        assert probe.headers["cache-control"] == "no-store, private"
        assert set(probe.json()) == {
            "problem",
            "answer_constraints",
            "expires_at",
            "instructions",
        }
        problem = probe.json()["problem"]
        submitted = await learner_client.post(
            f"/v1/respond/{token}",
            headers={"Idempotency-Key": "learner-submit-key"},
            json={"answer": problem["a"] - problem["b"]},
        )
        assert submitted.status_code == 200
        assert submitted.headers["referrer-policy"] == "no-referrer"
        assert submitted.headers["cache-control"] == "no-store, private"

    pending = await client.get(f"/v1/workflows/{identifiers['workflow_id']}")
    assert {item["status"] for item in pending.json()["deterministic_evidence"]} == {
        "weakened"
    }
    reviewed = await client.post(
        f"/v1/workflows/{identifiers['workflow_id']}/review",
        headers={"Idempotency-Key": "teacher-review-key"},
        json={
            "expected_version": pending.json()["version"],
            "decision": "approved",
            "note": "Teacher reviewed this bounded proposal.",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "APPROVED"
    assert reviewed.json()["review_result"] == {
        "decision": "approved",
        "note": "Teacher reviewed this bounded proposal.",
        "edited_text": None,
        "created_at": reviewed.json()["review_result"]["created_at"],
    }
    audit = await client.get(f"/v1/workflows/{identifiers['workflow_id']}/audit")
    assert audit.status_code == 200
    assert [event["version"] for event in audit.json()["events"]] == list(range(1, 9))


@pytest.mark.postgres
async def test_cross_owner_access_returns_same_non_enumerating_404(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={OWNER_COOKIE_NAME: generate_secret()},
    ) as first, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={OWNER_COOKIE_NAME: generate_secret()},
    ) as second:
        created = await first.post(
            "/v1/cases", headers={"Idempotency-Key": "first-owner-key"}, json=case_payload()
        )
        await second.post(
            "/v1/cases", headers={"Idempotency-Key": "second-owner-key"}, json=case_payload()
        )
        workflow_id = created.json()["workflow_id"]
        cross_owner = await second.get(f"/v1/workflows/{workflow_id}")
        missing_owner = await httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ).get(f"/v1/workflows/{workflow_id}")
    assert cross_owner.status_code == missing_owner.status_code == 404
    assert cross_owner.json() == missing_owner.json() == {"detail": "resource not found"}


@pytest.mark.postgres
async def test_production_owner_cookie_is_hardened(db_engine, db_session):
    del db_session
    settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://cognisect:cognisect@localhost:54329/cognisect",
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        public_app_url="https://cognisect.example",
        openai_api_key="sk-test-" + ("k" * 32),
    )
    production_app = create_app(
        settings=settings,
        session_factory=create_session_factory(db_engine),
        analyzer=ApiAnalyzer(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=production_app), base_url="https://cognisect.example"
    ) as production_client:
        response = await production_client.post(
            "/v1/cases", headers={"Idempotency-Key": "production-create-key"}, json=case_payload()
        )
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


@pytest.mark.postgres
async def test_teacher_can_decline_probe_into_abstained_without_creating_token(client):
    created = await client.post(
        "/v1/cases", headers={"Idempotency-Key": "decline-create-key"}, json=case_payload()
    )
    identifiers = created.json()
    analyzed = await client.post(
        f"/v1/cases/{identifiers['case_id']}/analysis",
        headers={"Idempotency-Key": "decline-analysis-key"},
        json={"expected_version": 0},
    )
    declined = await client.post(
        f"/v1/workflows/{identifiers['workflow_id']}/probe-approval",
        headers={"Idempotency-Key": "decline-probe-key"},
        json={"expected_version": analyzed.json()["version"], "approved": False},
    )
    assert declined.status_code == 200
    assert declined.json()["response_url"] is None
    assert declined.json()["expires_at"] is None
    assert declined.json()["workflow"]["state"] == "ABSTAINED"


@pytest.mark.postgres
async def test_delete_exact_replay_is_204_and_cross_owner_resource_stays_private(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={OWNER_COOKIE_NAME: generate_secret()},
    ) as first, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={OWNER_COOKIE_NAME: generate_secret()},
    ) as second:
        first_case = await first.post(
            "/v1/cases", headers={"Idempotency-Key": "delete-first-create"}, json=case_payload()
        )
        second_case = await second.post(
            "/v1/cases", headers={"Idempotency-Key": "delete-second-create"}, json=case_payload()
        )
        first_workflow_id = first_case.json()["workflow_id"]
        second_workflow_id = second_case.json()["workflow_id"]

        deleted = await first.delete(
            f"/v1/workflows/{first_workflow_id}",
            headers={"Idempotency-Key": "delete-exact-key"},
        )
        replayed = await first.delete(
            f"/v1/workflows/{first_workflow_id}",
            headers={"Idempotency-Key": "delete-exact-key"},
        )
        changed_key = await first.delete(
            f"/v1/workflows/{first_workflow_id}",
            headers={"Idempotency-Key": "delete-changed-key"},
        )
        cross_owner = await first.delete(
            f"/v1/workflows/{second_workflow_id}",
            headers={"Idempotency-Key": "delete-exact-key"},
        )
        second_still_exists = await second.get(f"/v1/workflows/{second_workflow_id}")

    assert deleted.status_code == 204
    assert replayed.status_code == 204
    assert changed_key.status_code == 404
    assert cross_owner.status_code == 404
    assert second_still_exists.status_code == 200


@pytest.mark.postgres
async def test_every_learner_response_error_has_privacy_headers(client, db_engine):
    not_found = await client.get("/v1/respond/not-a-valid-token")
    unprocessable = await client.post(
        "/v1/respond/not-a-valid-token",
        headers={"Idempotency-Key": "privacy-invalid-key"},
        json={"answer": "not-an-integer"},
    )

    conflict_token = await issue_learner_token(client, "privacy-conflict")
    probe = await client.get(f"/v1/respond/{conflict_token}")
    problem = probe.json()["problem"]
    await client.post(
        f"/v1/respond/{conflict_token}",
        headers={"Idempotency-Key": "privacy-submit-first"},
        json={"answer": problem["a"] - problem["b"]},
    )
    conflict = await client.post(
        f"/v1/respond/{conflict_token}",
        headers={"Idempotency-Key": "privacy-submit-second"},
        json={"answer": 17},
    )

    expired_token = await issue_learner_token(client, "privacy-expired")
    expired_hash = hash_secret(expired_token, "l" * 32, purpose="learner-token")
    factory = create_session_factory(db_engine)
    async with factory() as session, session.begin():
        await session.execute(
            update(LearnerTokenRecord)
            .where(LearnerTokenRecord.token_hash == expired_hash)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    gone = await client.get(f"/v1/respond/{expired_token}")

    assert [not_found.status_code, conflict.status_code, gone.status_code] == [404, 409, 410]
    assert unprocessable.status_code == 404
    for response in (not_found, unprocessable, conflict, gone):
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store, private"


@pytest.mark.postgres
async def test_invalid_answer_is_token_authorized_idempotent_and_content_free(
    client, db_engine
):
    token = await issue_learner_token(client, "invalid-answer")
    other_token = await issue_learner_token(client, "invalid-answer-other")
    marker = "PRIVATE-INVALID-ANSWER"

    first = await client.post(
        f"/v1/respond/{token}",
        headers={"Idempotency-Key": "invalid-answer-key"},
        json={"answer": marker},
    )
    replay = await client.post(
        f"/v1/respond/{token}",
        headers={"Idempotency-Key": "invalid-answer-key"},
        json={"answer": 10_001},
    )
    conflict = await client.post(
        f"/v1/respond/{token}",
        headers={"Idempotency-Key": "invalid-other-key"},
        json={"answer": []},
    )
    other_probe = await client.get(f"/v1/respond/{other_token}")

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert conflict.status_code == 409
    assert other_probe.status_code == 200
    factory = create_session_factory(db_engine)
    async with factory() as session:
        token_hash = hash_secret(token, "l" * 32, purpose="learner-token")
        token_record = await session.scalar(
            select(LearnerTokenRecord).where(LearnerTokenRecord.token_hash == token_hash)
        )
        assert token_record is not None
        workflow = await session.get(WorkflowRecord, token_record.workflow_id)
        invalid = await session.scalar(select(InvalidLearnerCommandRecord))
        response_count = await session.scalar(select(func.count(LearnerResponseRecord.id)))
    assert workflow is not None and workflow.state == "ABSTAINED"
    assert invalid is not None
    assert marker not in repr(invalid)
    assert response_count == 0


@pytest.mark.postgres
async def test_no_cookie_case_post_bootstraps_empty_owner_and_returns_428(app, db_engine):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as anonymous:
        response = await anonymous.post(
            "/v1/cases",
            headers={"Idempotency-Key": "must-not-be-authority"},
            json=case_payload(),
        )

    assert response.status_code == 428
    assert response.headers["cache-control"] == "no-store, private"
    cookie = response.headers["set-cookie"]
    assert OWNER_COOKIE_NAME in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.scalar(select(func.count(OwnerRecord.id))) == 1
        assert await session.scalar(select(func.count(CaseRecord.id))) == 0
        assert await session.scalar(select(func.count(WorkflowRecord.id))) == 0
        owner = await session.scalar(select(OwnerRecord))
    assert owner is not None
    assert "must-not-be-authority" not in owner.secret_hash


@pytest.mark.postgres
async def test_preestablished_owner_survives_commit_response_loss_with_one_case(
    app, db_engine
):
    owner_secret = generate_secret()
    headers = {"Idempotency-Key": "lost-create-response"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={OWNER_COOKIE_NAME: owner_secret},
    ) as first_process:
        committed_but_lost = await first_process.post(
            "/v1/cases", headers=headers, json=case_payload()
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        cookies={OWNER_COOKIE_NAME: owner_secret},
    ) as restarted_process:
        replayed = await restarted_process.post(
            "/v1/cases", headers=headers, json=case_payload()
        )

    assert committed_but_lost.status_code == replayed.status_code == 201
    assert committed_but_lost.json() == replayed.json()
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.scalar(select(func.count(OwnerRecord.id))) == 1
        assert await session.scalar(select(func.count(CaseRecord.id))) == 1
        assert await session.scalar(select(func.count(WorkflowRecord.id))) == 1
        owner = await session.scalar(select(OwnerRecord))
    assert owner is not None
    assert owner.secret_hash == hash_secret(owner_secret, "o" * 32, purpose="owner")


@pytest.mark.postgres
async def test_concurrent_first_registration_replays_one_case(app, db_engine):
    owner_secret = generate_secret()

    async def create() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            cookies={OWNER_COOKIE_NAME: owner_secret},
        ) as caller:
            return await caller.post(
                "/v1/cases",
                headers={"Idempotency-Key": "concurrent-first-registration"},
                json=case_payload(),
            )

    first, second = await asyncio.gather(create(), create())

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    factory = create_session_factory(db_engine)
    async with factory() as session:
        assert await session.scalar(select(func.count(OwnerRecord.id))) == 1
        assert await session.scalar(select(func.count(CaseRecord.id))) == 1
        assert await session.scalar(select(func.count(WorkflowRecord.id))) == 1


@pytest.mark.postgres
async def test_owner_read_recovers_only_an_active_unanswered_learner_url(client):
    created = await client.post(
        "/v1/cases",
        headers={"Idempotency-Key": "recover-link-create"},
        json=case_payload(),
    )
    identifiers = created.json()
    analyzed = await client.post(
        f"/v1/cases/{identifiers['case_id']}/analysis",
        headers={"Idempotency-Key": "recover-link-analysis"},
        json={"expected_version": 0},
    )
    approved = await client.post(
        f"/v1/workflows/{identifiers['workflow_id']}/probe-approval",
        headers={"Idempotency-Key": "recover-link-approval"},
        json={"expected_version": analyzed.json()["version"], "approved": True},
    )
    response_url = approved.json()["response_url"]

    recovered = await client.get(f"/v1/workflows/{identifiers['workflow_id']}")
    token = urlparse(response_url).path.rsplit("/", 1)[-1]
    audit = await client.get(f"/v1/workflows/{identifiers['workflow_id']}/audit")
    assert recovered.json()["learner_response_url"] == response_url
    assert recovered.headers["cache-control"] == "no-store, private"
    assert recovered.headers["referrer-policy"] == "no-referrer"
    assert token not in audit.text

    learner = await client.get(f"/v1/respond/{token}")
    problem = learner.json()["problem"]
    submitted = await client.post(
        f"/v1/respond/{token}",
        headers={"Idempotency-Key": "recover-link-submit"},
        json={"answer": problem["a"] - problem["b"]},
    )
    assert submitted.status_code == 200
    consumed = await client.get(f"/v1/workflows/{identifiers['workflow_id']}")
    assert consumed.json()["learner_response_url"] is None


@pytest.mark.postgres
@pytest.mark.parametrize(
    "payload",
    [
        {"answer": 1, "rationale": "x" * 1_001},
        {"answer": 1, "unexpected": "field"},
        {"answer": "invalid", "unexpected": "field"},
        ["not", "an", "object"],
    ],
)
async def test_non_answer_validation_errors_are_422_without_abstaining(
    client, db_engine, payload
):
    token = await issue_learner_token(client, f"validation-{abs(hash(str(payload)))}")
    token_hash = hash_secret(token, "l" * 32, purpose="learner-token")
    factory = create_session_factory(db_engine)
    async with factory() as session:
        token_record = await session.scalar(
            select(LearnerTokenRecord).where(LearnerTokenRecord.token_hash == token_hash)
        )
        assert token_record is not None
        workflow_id = token_record.workflow_id

    response = await client.post(
        f"/v1/respond/{token}",
        headers={"Idempotency-Key": "non-answer-validation"},
        json=payload,
    )
    workflow = await client.get(f"/v1/workflows/{workflow_id}")

    assert response.status_code == 422
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store, private"
    assert workflow.json()["state"] == "AWAITING_RESPONSE"
    assert workflow.json()["version"] == 3


@pytest.mark.postgres
async def test_owner_read_omits_expired_and_invalidated_learner_urls(client, db_engine):
    expired_token = await issue_learner_token(client, "recover-expired")
    expired_hash = hash_secret(expired_token, "l" * 32, purpose="learner-token")
    factory = create_session_factory(db_engine)
    async with factory() as session, session.begin():
        expired_record = await session.scalar(
            select(LearnerTokenRecord).where(LearnerTokenRecord.token_hash == expired_hash)
        )
        assert expired_record is not None
        expired_workflow_id = expired_record.workflow_id
        expired_record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    expired = await client.get(f"/v1/workflows/{expired_workflow_id}")
    assert expired.json()["learner_response_url"] is None

    invalid_token = await issue_learner_token(client, "recover-invalid")
    invalid_hash = hash_secret(invalid_token, "l" * 32, purpose="learner-token")
    async with factory() as session:
        invalid_record = await session.scalar(
            select(LearnerTokenRecord).where(LearnerTokenRecord.token_hash == invalid_hash)
        )
        assert invalid_record is not None
        invalid_workflow_id = invalid_record.workflow_id
    invalid = await client.post(
        f"/v1/respond/{invalid_token}",
        headers={"Idempotency-Key": "recover-invalid-answer"},
        json={"answer": "invalid"},
    )
    assert invalid.status_code == 200
    invalidated = await client.get(f"/v1/workflows/{invalid_workflow_id}")
    assert invalidated.json()["learner_response_url"] is None


@pytest.mark.postgres
async def test_malformed_learner_body_is_422_without_state_change(client, db_engine):
    token = await issue_learner_token(client, "malformed-body")
    token_hash = hash_secret(token, "l" * 32, purpose="learner-token")
    factory = create_session_factory(db_engine)
    async with factory() as session:
        token_record = await session.scalar(
            select(LearnerTokenRecord).where(LearnerTokenRecord.token_hash == token_hash)
        )
        assert token_record is not None
        workflow_id = token_record.workflow_id

    response = await client.post(
        f"/v1/respond/{token}",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "malformed-body-key",
        },
        content="{",
    )
    workflow = await client.get(f"/v1/workflows/{workflow_id}")

    assert response.status_code == 422
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store, private"
    assert workflow.json()["state"] == "AWAITING_RESPONSE"
    assert workflow.json()["version"] == 3
