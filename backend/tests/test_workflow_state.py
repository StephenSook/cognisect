"""Pure workflow transition and logging-safety contracts."""

from __future__ import annotations

import json

import pytest
import structlog

from cognisect.safe_logging import configure_logging, safe_event
from cognisect.workflow import ALLOWED_TRANSITIONS, TerminalStateError, WorkflowState, next_state


def test_allowed_transition_map_matches_the_frozen_state_machine():
    assert {
        WorkflowState.CREATED: {
            WorkflowState.ANALYZING,
            WorkflowState.ABSTAINED,
            WorkflowState.FAILED,
        },
        WorkflowState.ANALYZING: {
            WorkflowState.PROBE_READY,
            WorkflowState.ABSTAINED,
            WorkflowState.FAILED,
        },
        WorkflowState.PROBE_READY: {
            WorkflowState.AWAITING_RESPONSE,
            WorkflowState.ABSTAINED,
            WorkflowState.FAILED,
        },
        WorkflowState.AWAITING_RESPONSE: {
            WorkflowState.RESPONSE_RECORDED,
            WorkflowState.ABSTAINED,
            WorkflowState.FAILED,
        },
        WorkflowState.RESPONSE_RECORDED: {
            WorkflowState.RESUME_PENDING,
            WorkflowState.ABSTAINED,
            WorkflowState.FAILED,
        },
        WorkflowState.RESUME_PENDING: {
            WorkflowState.UPDATING,
            WorkflowState.ABSTAINED,
            WorkflowState.FAILED,
        },
        WorkflowState.UPDATING: {
            WorkflowState.AWAITING_REVIEW,
            WorkflowState.ABSTAINED,
            WorkflowState.FAILED,
        },
        WorkflowState.AWAITING_REVIEW: {
            WorkflowState.APPROVED,
            WorkflowState.EDITED,
            WorkflowState.REJECTED,
            WorkflowState.ABSTAINED,
            WorkflowState.FAILED,
        },
        WorkflowState.APPROVED: set(),
        WorkflowState.EDITED: set(),
        WorkflowState.REJECTED: set(),
        WorkflowState.ABSTAINED: set(),
        WorkflowState.FAILED: set(),
    } == ALLOWED_TRANSITIONS


@pytest.mark.parametrize(
    "state",
    [
        WorkflowState.APPROVED,
        WorkflowState.EDITED,
        WorkflowState.REJECTED,
        WorkflowState.ABSTAINED,
        WorkflowState.FAILED,
    ],
)
def test_terminal_states_cannot_transition(state):
    with pytest.raises(TerminalStateError):
        next_state(state, WorkflowState.ANALYZING)


def test_structured_log_allowlist_drops_sensitive_values_and_keys():
    secrets = {
        "owner_secret": "OWNER-RAW-VALUE",
        "learner_token": "LEARNER-RAW-VALUE",
        "answer": -37,
        "rationale": "private rationale",
        "observed_work": "private observed work",
        "teacher_note": "private teacher note",
    }
    rendered = json.dumps(
        safe_event(
            "learner_response_recorded",
            workflow_id="wf-public-id",
            state="RESPONSE_RECORDED",
            **secrets,
        )
    )
    assert "wf-public-id" in rendered
    assert "RESPONSE_RECORDED" in rendered
    for value in secrets.values():
        assert str(value) not in rendered
    for key in secrets:
        assert key not in rendered


def test_captured_json_logs_never_contain_sensitive_values(capsys):
    configure_logging()
    sensitive = {
        "owner_secret": "OWNER-RAW-CAPABILITY",
        "learner_token": "LEARNER-RAW-CAPABILITY",
        "answer": 9876,
        "rationale": "RATIONALE-PRIVATE-TEXT",
        "observed_work": "OBSERVED-WORK-PRIVATE-TEXT",
        "teacher_note": "TEACHER-NOTE-PRIVATE-TEXT",
    }
    structlog.get_logger().info(
        "request_completed",
        workflow_id="safe-workflow-id",
        status_code=200,
        **sensitive,
    )
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert "safe-workflow-id" in rendered
    for value in sensitive.values():
        assert str(value) not in rendered
