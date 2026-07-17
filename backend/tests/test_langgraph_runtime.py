"""Real LangGraph/Postgres checkpoint restart and privacy contracts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy import text

from cognisect.api_models import CreateCaseRequest
from cognisect.config import Settings
from cognisect.database import create_session_factory
from cognisect.db_models import CaseRecord, OwnerRecord, WorkflowRecord
from cognisect.services import RetentionService, WorkflowService
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


async def persist_graph_workflow(factory, workflow_id, thread_id) -> None:
    """Create the application lifecycle row required before any saver command."""
    async with factory() as session, session.begin():
        owner = OwnerRecord(secret_hash=uuid4().hex * 2)
        session.add(owner)
        await session.flush()
        case = CaseRecord(
            owner_id=owner.id,
            source_tier="custom",
            original_a=-3,
            original_b=5,
            observed_work="-3 - 5 = 2",
            deidentified_attestation=True,
        )
        session.add(case)
        await session.flush()
        session.add(
            WorkflowRecord(
                id=workflow_id,
                case_id=case.id,
                owner_id=owner.id,
                thread_id=thread_id,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "kwargs", "phase"),
    [
        ("start_probe_interrupt", {}, "probe"),
        ("resume_probe", {"approved": True}, "probe"),
        ("resume_review", {"decision": "approved"}, "update"),
    ],
)
async def test_pending_snapshots_advance_with_none_instead_of_false_completed_noop(
    command, kwargs, phase
) -> None:
    class RecordingGraph:
        def __init__(self) -> None:
            self.inputs = []

        async def ainvoke(self, value, _config):
            self.inputs.append(value)
            return {"advanced": True}

    runtime = object.__new__(WorkflowGraphRuntime)
    graph = RecordingGraph()
    runtime._graph = graph
    state_reads = 0

    async def pending_state(_thread_id):
        nonlocal state_reads
        state_reads += 1
        kind = "probe_approval" if command == "resume_probe" else "teacher_review"
        if state_reads > 1:
            return SimpleNamespace(
                interrupts=(SimpleNamespace(value={"kind": kind}),),
                next=(),
                values={"workflow_id": str(workflow_id), "phase": phase},
            )
        return SimpleNamespace(
            interrupts=(),
            next=("pending_node",),
            values={"workflow_id": str(uuid4()), "phase": phase},
        )

    runtime.get_state = pending_state
    workflow_id = uuid4()
    thread_id = uuid4()
    method = getattr(runtime, command)
    result = (
        await method(workflow_id, thread_id, _lock_held=True, **kwargs)
        if command == "start_probe_interrupt"
        else await method(thread_id, _lock_held=True, **kwargs)
    )

    assert result == {"advanced": True}
    if command == "start_probe_interrupt":
        assert graph.inputs == [None]
    else:
        assert graph.inputs[0] is None
        assert isinstance(graph.inputs[1], Command)


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
    await persist_graph_workflow(factory, workflow_id, thread_id)
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

    factory = create_session_factory(db_engine)
    await persist_graph_workflow(factory, workflow_id, thread_id)
    runtime = WorkflowGraphRuntime(factory, checkpointer, update_action=update_action)
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

    factory = create_session_factory(db_engine)
    await persist_graph_workflow(factory, workflow_id, thread_id)
    runtime = WorkflowGraphRuntime(factory, checkpointer, update_action=crash_once)
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
    factory = create_session_factory(db_engine)
    await persist_graph_workflow(factory, workflow_id, thread_id)
    runtime = WorkflowGraphRuntime(
        factory,
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
    factory = create_session_factory(db_engine)
    await persist_graph_workflow(factory, workflow_id, thread_id)
    runtime = WorkflowGraphRuntime(
        factory,
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


@pytest.mark.postgres
async def test_deletion_waits_for_inflight_graph_then_purges_every_checkpoint(
    checkpointer, db_engine
) -> None:
    factory = create_session_factory(db_engine)
    settings = Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        abuse_key_pepper="a" * 32,
        proxy_signing_secret="p" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="",
    )
    service = WorkflowService(factory, settings, analyzer=None)
    created = await service.create_case(
        CreateCaseRequest(
            source_tier="custom",
            problem={"a": -3, "b": 5},
            observed_work="-3 - 5 = 2",
            deidentified_attestation=True,
        ),
        idempotency_key="lock-create",
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_update(_workflow_id):
        started.set()
        await release.wait()

    runtime = WorkflowGraphRuntime(factory, checkpointer, update_action=blocking_update)
    service.attach_graph_runtime(runtime)
    async with factory() as session:
        workflow = await session.get(WorkflowRecord, created.workflow_id)
        assert workflow is not None
        thread_id = workflow.thread_id

    graph_task = asyncio.create_task(
        runtime.resume_after_response(created.workflow_id, thread_id)
    )
    await started.wait()
    deletion_task = asyncio.create_task(
        service.delete_workflow(
            owner_secret=created.owner_secret,
            workflow_id=created.workflow_id,
            idempotency_key="lock-delete",
        )
    )
    await asyncio.sleep(0.05)
    assert not deletion_task.done()
    release.set()
    await graph_task
    await deletion_task

    async with factory() as session:
        assert await session.get(WorkflowRecord, created.workflow_id) is None
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE thread_id = :thread_id"),
                {"thread_id": str(thread_id)},
            )
            assert count == 0


@pytest.mark.postgres
async def test_graph_commands_after_committed_deletion_never_recreate_checkpoints(
    checkpointer, db_engine
) -> None:
    factory = create_session_factory(db_engine)
    settings = Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        owner_secret_pepper="o" * 32,
        learner_token_pepper="l" * 32,
        abuse_key_pepper="a" * 32,
        proxy_signing_secret="p" * 32,
        public_app_url="http://localhost:3000",
        openai_api_key="",
    )
    service = WorkflowService(factory, settings, analyzer=None)
    created = await service.create_case(
        CreateCaseRequest(
            source_tier="custom",
            problem={"a": -3, "b": 5},
            observed_work="-3 - 5 = 2",
            deidentified_attestation=True,
        ),
        idempotency_key="post-delete-create",
    )
    runtime = WorkflowGraphRuntime(
        factory,
        checkpointer,
        update_action=lambda _workflow_id: None,
    )
    service.attach_graph_runtime(runtime)
    async with factory() as session:
        workflow = await session.get(WorkflowRecord, created.workflow_id)
        assert workflow is not None
        thread_id = workflow.thread_id
    await service.delete_workflow(
        owner_secret=created.owner_secret,
        workflow_id=created.workflow_id,
        idempotency_key="post-delete-delete",
    )

    assert await runtime.start_probe_interrupt(created.workflow_id, thread_id) == {}
    assert await runtime.resume_probe(thread_id, approved=True) == {}
    assert await runtime.resume_after_response(created.workflow_id, thread_id) == {}
    assert await runtime.resume_review(thread_id, decision="approved") == {}

    async with factory() as session:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            count = await session.scalar(
                text(f"SELECT count(*) FROM {table} WHERE thread_id = :thread_id"),
                {"thread_id": str(thread_id)},
            )
            assert count == 0


@pytest.mark.postgres
async def test_graph_operation_bound_leaves_pool_capacity_for_update_nodes(
    checkpointer, db_engine
) -> None:
    factory = create_session_factory(db_engine)
    operation_count = 6
    started_count = 0
    four_started = asyncio.Event()
    release = asyncio.Event()

    async def connection_using_update(_workflow_id):
        nonlocal started_count
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        started_count += 1
        if started_count == 4:
            four_started.set()
        await release.wait()

    runtime = WorkflowGraphRuntime(
        factory,
        checkpointer,
        update_action=connection_using_update,
    )
    identifiers = [(uuid4(), uuid4()) for _ in range(operation_count)]
    for workflow_id, thread_id in identifiers:
        await persist_graph_workflow(factory, workflow_id, thread_id)
    tasks = [
        asyncio.create_task(runtime.resume_after_response(workflow_id, thread_id))
        for workflow_id, thread_id in identifiers
    ]

    await asyncio.wait_for(four_started.wait(), timeout=2)
    await asyncio.sleep(0.05)
    assert started_count == 4
    release.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=3)

    assert len(results) == operation_count
    assert started_count == operation_count
