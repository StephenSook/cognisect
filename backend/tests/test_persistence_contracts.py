"""Postgres schema and repository contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

from cognisect.db_models import (
    AcceptedHypothesisRecord,
    AnalysisStepResultRecord,
    AuditEventRecord,
    Base,
    CaseRecord,
    CompiledProbeRecord,
    DeletionAuditTombstoneRecord,
    GeneratedProposalRecord,
    IdempotencyRecord,
    InvalidLearnerCommandRecord,
    LearnerReceiptRecord,
    LearnerResponseRecord,
    LearnerTokenRecord,
    ModelCallRecord,
    OwnerRecord,
    ProbePredictionRecord,
    TeacherReviewRecord,
    WorkflowRecord,
)
from cognisect.repositories import (
    ConcurrentWriteError,
    OwnedResourceNotFoundError,
    transition_workflow,
)
from cognisect.workflow import WorkflowState

EXPECTED_TABLES = {
    "accepted_hypotheses",
    "analysis_step_results",
    "audit_events",
    "cases",
    "compiled_probes",
    "deletion_audit_tombstones",
    "generated_proposals",
    "idempotency_records",
    "invalid_learner_commands",
    "learner_receipts",
    "learner_responses",
    "learner_tokens",
    "model_calls",
    "owners",
    "probe_predictions",
    "teacher_reviews",
    "workflows",
}


def test_metadata_has_every_required_record_type():
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert {
        OwnerRecord,
        CaseRecord,
        WorkflowRecord,
        AcceptedHypothesisRecord,
        AnalysisStepResultRecord,
        CompiledProbeRecord,
        ProbePredictionRecord,
        LearnerTokenRecord,
        LearnerResponseRecord,
        LearnerReceiptRecord,
        GeneratedProposalRecord,
        TeacherReviewRecord,
        ModelCallRecord,
        IdempotencyRecord,
        InvalidLearnerCommandRecord,
        AuditEventRecord,
    }


def test_schema_never_has_raw_owner_or_learner_secret_columns():
    owner_columns = set(inspect(OwnerRecord).columns.keys())
    token_columns = set(inspect(LearnerTokenRecord).columns.keys())
    assert "secret_hash" in owner_columns
    assert "token_hash" in token_columns
    assert "derivation_nonce" in token_columns
    assert {"secret", "owner_secret", "raw_secret"}.isdisjoint(owner_columns)
    assert {"token", "learner_token", "raw_token"}.isdisjoint(token_columns)


def test_replay_metadata_is_hash_only_and_probe_hashes_are_not_global_ids():
    receipt_columns = set(inspect(LearnerReceiptRecord).columns.keys())
    tombstone_columns = set(inspect(DeletionAuditTombstoneRecord).columns.keys())
    probe_unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in inspect(CompiledProbeRecord).local_table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert {"idempotency_key_hash", "request_hash"} <= receipt_columns
    assert "replay_hash" in tombstone_columns
    assert ("specification_hash",) not in probe_unique_columns


def test_generated_and_teacher_edited_text_are_separate_records():
    generated_columns = set(inspect(GeneratedProposalRecord).columns.keys())
    review_columns = set(inspect(TeacherReviewRecord).columns.keys())
    assert "generated_text" in generated_columns
    assert "edited_text" not in generated_columns
    assert "edited_text" in review_columns
    assert "generated_text" not in review_columns


def test_case_provenance_is_a_nullable_column_for_historical_rows() -> None:
    provenance_column = inspect(CaseRecord).columns.provenance_record_id
    assert provenance_column.nullable is True
    assert provenance_column.type.length == 80


@pytest.mark.postgres
async def test_case_provenance_migration_preserves_historical_rows_as_null(
    db_engine, monkeypatch
) -> None:
    owner_id = UUID("00000000-0000-4000-8000-000000000301")
    case_id = UUID("00000000-0000-4000-8000-000000000302")
    alembic_config = Config("alembic.ini")
    monkeypatch.setenv(
        "COGNISECT_DATABASE_URL",
        db_engine.url.render_as_string(hide_password=False),
    )

    await db_engine.dispose()
    command.downgrade(alembic_config, "a61bd8e7c204")
    try:
        async with db_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO owners (id, secret_hash, created_at) "
                    "VALUES (:id, :secret_hash, now())"
                ),
                {"id": owner_id, "secret_hash": "3" * 64},
            )
            await connection.execute(
                text(
                    "INSERT INTO cases "
                    "(id, owner_id, source_tier, original_a, original_b, observed_work, "
                    "deidentified_attestation, created_at, updated_at) "
                    "VALUES (:id, :owner_id, 'educator_authored', -3, 5, '-3 - 5 = 2', "
                    "false, now(), now())"
                ),
                {"id": case_id, "owner_id": owner_id},
            )

        await db_engine.dispose()
        command.upgrade(alembic_config, "head")
        async with db_engine.connect() as connection:
            historical_case = (
                await connection.execute(
                    text("SELECT provenance_record_id FROM cases WHERE id = :id"),
                    {"id": case_id},
                )
            ).one()
        assert historical_case.provenance_record_id is None
    finally:
        await db_engine.dispose()
        command.upgrade(alembic_config, "head")
        async with db_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM owners WHERE id = :id"),
                {"id": owner_id},
            )


def test_model_attempt_journal_has_stable_content_free_identity_and_staged_results():
    call_columns = set(inspect(ModelCallRecord).columns.keys())
    result_columns = set(inspect(AnalysisStepResultRecord).columns.keys())
    call_uniques = {
        tuple(constraint.columns.keys())
        for constraint in inspect(ModelCallRecord).local_table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert {
        "attempt_ordinal",
        "purpose",
        "repair",
        "client_request_id",
        "finalized_at",
    } <= call_columns
    assert ("workflow_id", "attempt_ordinal") in call_uniques
    assert {"workflow_id", "attempt_ordinal", "purpose", "schema_version", "payload"} <= (
        result_columns
    )
    assert {"prompt", "response", "observed_work"}.isdisjoint(call_columns)


@pytest.mark.postgres
async def test_transition_uses_compare_and_swap_and_appends_one_event(db_session, seeded_workflow):
    workflow, owner = seeded_workflow
    workflow_id = workflow.id
    await transition_workflow(
        db_session,
        workflow_id=workflow_id,
        owner_id=owner.id,
        expected_version=0,
        requested_state=WorkflowState.ANALYZING,
        event_key="analysis-start-key",
    )
    await db_session.commit()

    db_session.expire_all()
    updated = await db_session.get(WorkflowRecord, workflow_id)
    events = (
        await db_session.scalars(
            select(AuditEventRecord).where(AuditEventRecord.workflow_id == workflow_id)
        )
    ).all()
    assert updated is not None
    assert (updated.state, updated.version) == (WorkflowState.ANALYZING, 1)
    assert [(event.from_state, event.to_state, event.version) for event in events] == [
        (WorkflowState.CREATED, WorkflowState.ANALYZING, 1)
    ]


@pytest.mark.postgres
async def test_stale_compare_and_swap_changes_nothing(db_session, seeded_workflow):
    workflow, owner = seeded_workflow
    await transition_workflow(
        db_session,
        workflow_id=workflow.id,
        owner_id=owner.id,
        expected_version=0,
        requested_state=WorkflowState.ANALYZING,
        event_key="first",
    )
    await db_session.commit()
    with pytest.raises(ConcurrentWriteError):
        await transition_workflow(
            db_session,
            workflow_id=workflow.id,
            owner_id=owner.id,
            expected_version=0,
            requested_state=WorkflowState.ANALYZING,
            event_key="stale",
        )


@pytest.mark.postgres
async def test_cross_owner_transition_is_a_non_enumerating_not_found(db_session, seeded_workflow):
    workflow, _owner = seeded_workflow
    with pytest.raises(OwnedResourceNotFoundError, match="resource not found"):
        await transition_workflow(
            db_session,
            workflow_id=workflow.id,
            owner_id=uuid4(),
            expected_version=0,
            requested_state=WorkflowState.ANALYZING,
            event_key="other-owner",
        )


@pytest.mark.postgres
async def test_audit_events_are_append_only_at_database_level(db_session, seeded_workflow):
    workflow, owner = seeded_workflow
    await transition_workflow(
        db_session,
        workflow_id=workflow.id,
        owner_id=owner.id,
        expected_version=0,
        requested_state=WorkflowState.ANALYZING,
        event_key="immutable",
    )
    await db_session.commit()
    event = await db_session.scalar(
        select(AuditEventRecord).where(AuditEventRecord.workflow_id == workflow.id)
    )
    assert event is not None
    event.occurred_at = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(DBAPIError, match="append-only"):
        await db_session.commit()
