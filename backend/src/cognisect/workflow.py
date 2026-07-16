"""Explicit durable workflow states and transition policy."""

from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    """All states in the frozen teacher-controlled workflow."""

    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PROBE_READY = "PROBE_READY"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    RESPONSE_RECORDED = "RESPONSE_RECORDED"
    RESUME_PENDING = "RESUME_PENDING"
    UPDATING = "UPDATING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset(
    {
        WorkflowState.APPROVED,
        WorkflowState.EDITED,
        WorkflowState.REJECTED,
        WorkflowState.ABSTAINED,
        WorkflowState.FAILED,
    }
)

_FAILURE_EDGES = {WorkflowState.ABSTAINED, WorkflowState.FAILED}
ALLOWED_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.CREATED: {WorkflowState.ANALYZING, *_FAILURE_EDGES},
    WorkflowState.ANALYZING: {WorkflowState.PROBE_READY, *_FAILURE_EDGES},
    WorkflowState.PROBE_READY: {WorkflowState.AWAITING_RESPONSE, *_FAILURE_EDGES},
    WorkflowState.AWAITING_RESPONSE: {WorkflowState.RESPONSE_RECORDED, *_FAILURE_EDGES},
    WorkflowState.RESPONSE_RECORDED: {WorkflowState.RESUME_PENDING, *_FAILURE_EDGES},
    WorkflowState.RESUME_PENDING: {WorkflowState.UPDATING, *_FAILURE_EDGES},
    WorkflowState.UPDATING: {WorkflowState.AWAITING_REVIEW, *_FAILURE_EDGES},
    WorkflowState.AWAITING_REVIEW: {
        WorkflowState.APPROVED,
        WorkflowState.EDITED,
        WorkflowState.REJECTED,
        *_FAILURE_EDGES,
    },
    **{state: set() for state in TERMINAL_STATES},
}


class WorkflowTransitionError(ValueError):
    """Base transition policy error with content-free text."""


class TerminalStateError(WorkflowTransitionError):
    """Raised when a command attempts to leave a terminal state."""


class InvalidTransitionError(WorkflowTransitionError):
    """Raised when a requested edge is absent from the frozen map."""


def next_state(current: WorkflowState, requested: WorkflowState) -> WorkflowState:
    """Validate one explicit state-machine edge."""
    if current in TERMINAL_STATES:
        msg = "terminal workflows cannot transition"
        raise TerminalStateError(msg)
    if requested not in ALLOWED_TRANSITIONS[current]:
        msg = "workflow transition is not allowed"
        raise InvalidTransitionError(msg)
    return requested
