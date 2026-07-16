"""Ownership-safe, compare-and-swap persistence primitives."""

from __future__ import annotations

import hashlib
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from cognisect.db_models import AuditEventRecord, WorkflowRecord, utc_now
from cognisect.workflow import WorkflowState, next_state


class PersistenceError(RuntimeError):
    """Content-free base error safe to expose through API mapping."""


class OwnedResourceNotFoundError(PersistenceError):
    """Non-enumerating ownership lookup failure."""


class ConcurrentWriteError(PersistenceError):
    """Optimistic version mismatch."""


def _event_key_hash(event_key: str) -> str:
    if not event_key:
        msg = "event key is required"
        raise ValueError(msg)
    return hashlib.sha256(event_key.encode()).hexdigest()


async def get_owned_workflow(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    owner_id: UUID,
) -> WorkflowRecord:
    """Return an owned workflow or the same 404-class error for every miss."""
    workflow = await session.scalar(
        select(WorkflowRecord).where(
            WorkflowRecord.id == workflow_id,
            WorkflowRecord.owner_id == owner_id,
        )
    )
    if workflow is None:
        msg = "resource not found"
        raise OwnedResourceNotFoundError(msg)
    return workflow


async def transition_workflow(  # noqa: PLR0913
    session: AsyncSession,
    *,
    workflow_id: UUID,
    owner_id: UUID,
    expected_version: int,
    requested_state: WorkflowState,
    event_key: str,
) -> WorkflowRecord:
    """Apply one atomic CAS edge and append exactly one immutable event."""
    key_hash = _event_key_hash(event_key)
    existing_event = await session.scalar(
        select(AuditEventRecord).where(
            AuditEventRecord.workflow_id == workflow_id,
            AuditEventRecord.event_key_hash == key_hash,
        )
    )
    if existing_event is not None:
        workflow = await get_owned_workflow(
            session, workflow_id=workflow_id, owner_id=owner_id
        )
        if existing_event.to_state != requested_state:
            msg = "idempotency key conflicts with an earlier transition"
            raise ConcurrentWriteError(msg)
        return workflow

    workflow = await get_owned_workflow(session, workflow_id=workflow_id, owner_id=owner_id)
    if workflow.version != expected_version:
        msg = "workflow version is stale"
        raise ConcurrentWriteError(msg)
    current_state = workflow.state
    next_state(current_state, requested_state)
    new_version = expected_version + 1
    result = cast(
        "CursorResult[tuple[()]]",
        await session.execute(
            update(WorkflowRecord)
            .where(
                WorkflowRecord.id == workflow_id,
                WorkflowRecord.owner_id == owner_id,
                WorkflowRecord.version == expected_version,
                WorkflowRecord.state == current_state,
            )
            .values(state=requested_state, version=new_version, updated_at=utc_now())
        )
    )
    if result.rowcount != 1:
        msg = "workflow version is stale"
        raise ConcurrentWriteError(msg)
    session.add(
        AuditEventRecord(
            workflow_id=workflow_id,
            sequence=new_version,
            from_state=current_state,
            to_state=requested_state,
            version=new_version,
            event_key_hash=key_hash,
        )
    )
    await session.flush()
    return await get_owned_workflow(session, workflow_id=workflow_id, owner_id=owner_id)
