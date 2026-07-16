"""Real LangGraph/Postgres checkpoint restart and privacy contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from cognisect.database import create_session_factory
from cognisect.db_models import CaseRecord
from cognisect.services import RetentionService
from cognisect.workflow_graph import (
    WorkflowGraphRuntime,
    checkpoint_connection_url,
    secure_checkpoint_serializer,
)
from conftest import TEST_DATABASE_URL


@pytest_asyncio.fixture
async def checkpointer(db_engine, db_session) -> AsyncIterator[AsyncPostgresSaver]:
    del db_engine, db_session
    async with AsyncPostgresSaver.from_conn_string(
        checkpoint_connection_url(TEST_DATABASE_URL),
        serde=secure_checkpoint_serializer(),
    ) as saver:
        await saver.setup()
        yield saver


def test_checkpoint_serializer_disables_pickle_and_arbitrary_module_loading() -> None:
    serializer = secure_checkpoint_serializer()

    assert serializer.pickle_fallback is False
    assert serializer._allowed_msgpack_modules is None
    assert serializer._allowed_json_modules is None


@pytest.mark.postgres
async def test_real_interrupts_resume_across_fresh_checkpointer_processes(db_engine, db_session):
    del db_session
    workflow_id = uuid4()
    thread_id = uuid4()
    updates: list[str] = []

    async def update_action(value):
        updates.append(str(value))

    connection_url = checkpoint_connection_url(TEST_DATABASE_URL)
    factory = create_session_factory(db_engine)
    async with AsyncPostgresSaver.from_conn_string(
        connection_url, serde=secure_checkpoint_serializer()
    ) as first_saver:
        await first_saver.setup()
        first = WorkflowGraphRuntime(factory, first_saver, update_action=update_action)
        probe_result = await first.start_probe_interrupt(workflow_id, thread_id)
        assert probe_result["__interrupt__"][0].value == {
            "kind": "probe_approval",
            "workflow_id": str(workflow_id),
        }

    async with AsyncPostgresSaver.from_conn_string(
        connection_url, serde=secure_checkpoint_serializer()
    ) as second_saver:
        second = WorkflowGraphRuntime(factory, second_saver, update_action=update_action)
        resumed = await second.resume_probe(thread_id, approved=True)
        assert "__interrupt__" not in resumed
        review_result = await second.resume_after_response(workflow_id, thread_id)
        assert review_result["__interrupt__"][0].value == {
            "kind": "teacher_review",
            "workflow_id": str(workflow_id),
        }

    async with AsyncPostgresSaver.from_conn_string(
        connection_url, serde=secure_checkpoint_serializer()
    ) as third_saver:
        third = WorkflowGraphRuntime(factory, third_saver, update_action=update_action)
        reviewed = await third.resume_review(thread_id, decision="approved")
        assert "__interrupt__" not in reviewed

    assert updates == [str(workflow_id)]


@pytest.mark.postgres
async def test_duplicate_response_resume_does_not_repeat_update_action(
    checkpointer, db_engine
) -> None:
    workflow_id = uuid4()
    thread_id = uuid4()
    updates: list[str] = []

    async def update_action(value):
        updates.append(str(value))

    runtime = WorkflowGraphRuntime(
        create_session_factory(db_engine), checkpointer, update_action=update_action
    )
    await runtime.resume_after_response(workflow_id, thread_id)
    duplicate = await runtime.resume_after_response(workflow_id, thread_id)

    assert duplicate["__interrupt__"][0].value["kind"] == "teacher_review"
    assert updates == [str(workflow_id)]


@pytest.mark.postgres
async def test_pending_update_task_recovers_instead_of_becoming_completed_noop(
    checkpointer, db_engine
) -> None:
    workflow_id = uuid4()
    thread_id = uuid4()
    attempts = 0

    async def crash_once(_workflow_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("simulated crash")

    runtime = WorkflowGraphRuntime(
        create_session_factory(db_engine),
        checkpointer,
        update_action=crash_once,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        await runtime.resume_after_response(workflow_id, thread_id)
    interrupted = await runtime.get_state(thread_id)
    assert interrupted.next

    recovered = await runtime.resume_after_response(workflow_id, thread_id)

    assert recovered["__interrupt__"][0].value["kind"] == "teacher_review"
    assert attempts == 2


@pytest.mark.postgres
async def test_duplicate_start_approval_and_review_are_checkpoint_noops(
    checkpointer, db_engine
) -> None:
    workflow_id = uuid4()
    thread_id = uuid4()
    runtime = WorkflowGraphRuntime(
        create_session_factory(db_engine),
        checkpointer,
        update_action=lambda _workflow_id: None,
    )
    first_start = await runtime.start_probe_interrupt(workflow_id, thread_id)
    async with create_session_factory(db_engine)() as session:
        after_start = await session.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
            {"thread_id": str(thread_id)},
        )
    duplicate_start = await runtime.start_probe_interrupt(workflow_id, thread_id)
    async with create_session_factory(db_engine)() as session:
        after_start_replay = await session.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
            {"thread_id": str(thread_id)},
        )
    assert first_start["__interrupt__"][0].value["kind"] == "probe_approval"
    assert duplicate_start["__interrupt__"][0].value["kind"] == "probe_approval"
    assert after_start_replay == after_start

    await runtime.resume_probe(thread_id, approved=True)
    async with create_session_factory(db_engine)() as session:
        after_approval = await session.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
            {"thread_id": str(thread_id)},
        )
    await runtime.resume_probe(thread_id, approved=True)
    async with create_session_factory(db_engine)() as session:
        after_approval_replay = await session.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
            {"thread_id": str(thread_id)},
        )
    assert after_approval_replay == after_approval

    await runtime.resume_after_response(workflow_id, thread_id)
    await runtime.resume_review(thread_id, decision="approved")
    async with create_session_factory(db_engine)() as session:
        after_review = await session.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
            {"thread_id": str(thread_id)},
        )
    await runtime.resume_review(thread_id, decision="approved")
    await runtime.resume_after_response(workflow_id, thread_id)
    async with create_session_factory(db_engine)() as session:
        after_review_replays = await session.scalar(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
            {"thread_id": str(thread_id)},
        )
    assert after_review_replays == after_review


@pytest.mark.postgres
async def test_checkpoint_state_is_content_minimal_and_thread_purge_removes_all_rows(
    checkpointer, db_engine
) -> None:
    workflow_id = uuid4()
    thread_id = uuid4()
    runtime = WorkflowGraphRuntime(
        create_session_factory(db_engine),
        checkpointer,
        update_action=lambda _workflow_id: None,
    )
    await runtime.start_probe_interrupt(workflow_id, thread_id)

    snapshot = await runtime.get_state(thread_id)
    assert snapshot.values == {"workflow_id": str(workflow_id), "phase": "probe"}
    assert "observed_work" not in repr(snapshot)
    assert "rationale" not in repr(snapshot)
    assert "prompt" not in repr(snapshot)

    await runtime.purge_thread(thread_id)

    async with create_session_factory(db_engine)() as session:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE thread_id = :thread_id"),
                {"thread_id": str(thread_id)},
            )
            assert count == 0


@pytest.mark.postgres
async def test_retention_purges_checkpoint_rows_in_the_content_transaction(
    checkpointer, db_engine, seeded_workflow
) -> None:
    workflow, _owner = seeded_workflow
    factory = create_session_factory(db_engine)
    runtime = WorkflowGraphRuntime(
        factory,
        checkpointer,
        update_action=lambda _workflow_id: None,
    )
    await runtime.start_probe_interrupt(workflow.id, workflow.thread_id)
    async with factory() as session, session.begin():
        case = await session.get(CaseRecord, workflow.case_id)
        assert case is not None
        case.created_at = datetime.now(UTC) - timedelta(days=31)

    retention = RetentionService(
        factory,
        retention_days=30,
        graph_runtime=runtime,
    )
    assert await retention.purge_expired(now=datetime.now(UTC)) == 1

    async with factory() as session:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE thread_id = :thread_id"),
                {"thread_id": str(workflow.thread_id)},
            )
            assert count == 0
