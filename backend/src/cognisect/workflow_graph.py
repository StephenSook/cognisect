"""Content-minimal LangGraph orchestration backed by Postgres checkpoints."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Final, Literal, TypedDict, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, StateSnapshot, interrupt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognisect.db_models import WorkflowRecord
from cognisect.lifecycle_lock import acquire_lifecycle_lock

_CHECKPOINT_DELETE_STATEMENTS: Final = (
    ("checkpoint_writes", text("DELETE FROM checkpoint_writes WHERE thread_id = :thread_id")),
    ("checkpoint_blobs", text("DELETE FROM checkpoint_blobs WHERE thread_id = :thread_id")),
    ("checkpoints", text("DELETE FROM checkpoints WHERE thread_id = :thread_id")),
)


class WorkflowGraphState(TypedDict):
    """The entire durable graph state; learner content stays in application tables."""

    workflow_id: str
    phase: Literal["probe", "update"]


UpdateAction = Callable[[UUID], Awaitable[None] | None]


def secure_checkpoint_serializer() -> JsonPlusSerializer:
    """Return the strict serializer required for untrusted checkpoint data."""
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_json_modules=None,
        allowed_msgpack_modules=None,
    )


def checkpoint_connection_url(database_url: str) -> str:
    """Translate SQLAlchemy's psycopg URL to the libpq URL expected by psycopg."""
    prefix = "postgresql+psycopg://"
    if not database_url.lower().startswith(prefix):
        msg = "checkpoint storage requires postgresql+psycopg"
        raise ValueError(msg)
    return "postgresql://" + database_url[len(prefix) :]


class WorkflowGraphRuntime:
    """Run the two durable human interrupts without checkpointing private content."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        checkpointer: AsyncPostgresSaver,
        *,
        update_action: UpdateAction,
    ) -> None:
        """Compile the stable two-interrupt graph with an injected update action."""
        self._session_factory = session_factory
        self._update_action = update_action

        builder = StateGraph(WorkflowGraphState)
        builder.add_node("probe_interrupt", self._probe_interrupt)
        builder.add_node("update", self._update)
        builder.add_node("review_interrupt", self._review_interrupt)
        builder.add_conditional_edges(
            START,
            self._route_phase,
            {"probe": "probe_interrupt", "update": "update"},
        )
        builder.add_edge("probe_interrupt", END)
        builder.add_edge("update", "review_interrupt")
        builder.add_edge("review_interrupt", END)
        self._graph = builder.compile(checkpointer=checkpointer)

    @staticmethod
    def _route_phase(state: WorkflowGraphState) -> Literal["probe", "update"]:
        return state["phase"]

    @staticmethod
    def _probe_interrupt(state: WorkflowGraphState) -> dict[str, object]:
        interrupt(
            {
                "kind": "probe_approval",
                "workflow_id": state["workflow_id"],
            }
        )
        return {}

    async def _update(self, state: WorkflowGraphState) -> dict[str, object]:
        result = self._update_action(UUID(state["workflow_id"]))
        if inspect.isawaitable(result):
            await result
        return {}

    @staticmethod
    def _review_interrupt(state: WorkflowGraphState) -> dict[str, object]:
        interrupt(
            {
                "kind": "teacher_review",
                "workflow_id": state["workflow_id"],
            }
        )
        return {}

    @staticmethod
    def _config(thread_id: UUID) -> RunnableConfig:
        return {"configurable": {"thread_id": str(thread_id)}}

    @staticmethod
    def _interrupt_result(
        snapshot: StateSnapshot,
        kind: str,
    ) -> dict[str, object] | None:
        matches = tuple(
            item
            for item in snapshot.interrupts
            if isinstance(item.value, dict) and item.value.get("kind") == kind
        )
        return {"__interrupt__": matches} if matches else None

    @staticmethod
    def _snapshot_result(snapshot: StateSnapshot) -> dict[str, object]:
        return cast("dict[str, object]", dict(snapshot.values))

    @staticmethod
    async def _workflow_exists(
        session: AsyncSession,
        thread_id: UUID,
        *,
        workflow_id: UUID | None = None,
    ) -> bool:
        statement = select(WorkflowRecord.id).where(WorkflowRecord.thread_id == thread_id)
        if workflow_id is not None:
            statement = statement.where(WorkflowRecord.id == workflow_id)
        return await session.scalar(statement) is not None

    async def start_probe_interrupt(
        self,
        workflow_id: UUID,
        thread_id: UUID,
        *,
        _lock_held: bool = False,
    ) -> dict[str, object]:
        """Start a workflow at the teacher's probe approval interrupt."""
        if not _lock_held:
            async with self._session_factory() as session, session.begin():
                await acquire_lifecycle_lock(session, thread_id)
                if not await self._workflow_exists(
                    session,
                    thread_id,
                    workflow_id=workflow_id,
                ):
                    return {}
                return await self.start_probe_interrupt(
                    workflow_id,
                    thread_id,
                    _lock_held=True,
                )
        snapshot = await self.get_state(thread_id)
        existing = self._interrupt_result(snapshot, "probe_approval")
        if existing is not None:
            return existing
        if snapshot.next:
            return cast(
                "dict[str, object]",
                await self._graph.ainvoke(None, self._config(thread_id)),
            )
        if snapshot.values:
            return self._snapshot_result(snapshot)
        return cast(
            "dict[str, object]",
            await self._graph.ainvoke(
                {"workflow_id": str(workflow_id), "phase": "probe"},
                self._config(thread_id),
            ),
        )

    async def resume_probe(
        self,
        thread_id: UUID,
        *,
        approved: bool,
        _lock_held: bool = False,
    ) -> dict[str, object]:
        """Resume the durable probe interrupt with a content-free decision."""
        if not _lock_held:
            async with self._session_factory() as session, session.begin():
                await acquire_lifecycle_lock(session, thread_id)
                if not await self._workflow_exists(session, thread_id):
                    return {}
                return await self.resume_probe(
                    thread_id,
                    approved=approved,
                    _lock_held=True,
                )
        snapshot = await self.get_state(thread_id)
        if self._interrupt_result(snapshot, "probe_approval") is None:
            if snapshot.next:
                await self._graph.ainvoke(None, self._config(thread_id))
                snapshot = await self.get_state(thread_id)
            if self._interrupt_result(snapshot, "probe_approval") is None:
                if snapshot.next:
                    msg = "probe approval recovery remains pending"
                    raise RuntimeError(msg)
                return self._snapshot_result(snapshot)
        return cast(
            "dict[str, object]",
            await self._graph.ainvoke(
                Command(resume={"approved": approved}), self._config(thread_id)
            ),
        )

    async def resume_after_response(
        self,
        workflow_id: UUID,
        thread_id: UUID,
        *,
        _lock_held: bool = False,
    ) -> dict[str, object]:
        """Run idempotent response updating, then stop at the review interrupt."""
        if not _lock_held:
            async with self._session_factory() as session, session.begin():
                await acquire_lifecycle_lock(session, thread_id)
                if not await self._workflow_exists(
                    session,
                    thread_id,
                    workflow_id=workflow_id,
                ):
                    return {}
                return await self.resume_after_response(
                    workflow_id,
                    thread_id,
                    _lock_held=True,
                )
        snapshot = await self.get_state(thread_id)
        existing = self._interrupt_result(snapshot, "teacher_review")
        if existing is not None:
            return existing
        if snapshot.values.get("phase") == "update":
            if not snapshot.next:
                return self._snapshot_result(snapshot)
            return cast(
                "dict[str, object]",
                await self._graph.ainvoke(None, self._config(thread_id)),
            )

        return cast(
            "dict[str, object]",
            await self._graph.ainvoke(
                {"workflow_id": str(workflow_id), "phase": "update"},
                self._config(thread_id),
            ),
        )

    async def resume_review(
        self,
        thread_id: UUID,
        *,
        decision: str,
        _lock_held: bool = False,
    ) -> dict[str, object]:
        """Resume the durable teacher review interrupt."""
        if not _lock_held:
            async with self._session_factory() as session, session.begin():
                await acquire_lifecycle_lock(session, thread_id)
                if not await self._workflow_exists(session, thread_id):
                    return {}
                return await self.resume_review(
                    thread_id,
                    decision=decision,
                    _lock_held=True,
                )
        snapshot = await self.get_state(thread_id)
        if self._interrupt_result(snapshot, "teacher_review") is None:
            if snapshot.next:
                await self._graph.ainvoke(None, self._config(thread_id))
                snapshot = await self.get_state(thread_id)
            if self._interrupt_result(snapshot, "teacher_review") is None:
                if snapshot.next:
                    msg = "teacher review recovery remains pending"
                    raise RuntimeError(msg)
                return self._snapshot_result(snapshot)
        return cast(
            "dict[str, object]",
            await self._graph.ainvoke(
                Command(resume={"decision": decision}), self._config(thread_id)
            ),
        )

    async def get_state(self, thread_id: UUID) -> StateSnapshot:
        """Return a durable snapshot for recovery and duplicate detection."""
        return await self._graph.aget_state(self._config(thread_id))

    async def purge_thread(
        self,
        thread_id: UUID,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        """Delete every checkpoint row belonging to one workflow thread."""
        if session is None:
            async with self._session_factory.begin() as owned_session:
                await acquire_lifecycle_lock(owned_session, thread_id)
                await self._purge_thread_rows(owned_session, thread_id)
            return
        await acquire_lifecycle_lock(session, thread_id)
        await self._purge_thread_rows(session, thread_id)

    @staticmethod
    async def _purge_thread_rows(session: AsyncSession, thread_id: UUID) -> None:
        parameters = {"thread_id": str(thread_id)}
        for table, statement in _CHECKPOINT_DELETE_STATEMENTS:
            exists = await session.scalar(
                text("SELECT to_regclass(:table_name)"), {"table_name": table}
            )
            if exists is not None:
                await session.execute(statement, parameters)
