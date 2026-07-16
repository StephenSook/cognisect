"""Structured JSON logging constrained to a public metadata allowlist."""

from __future__ import annotations

from collections.abc import Mapping

import structlog

_ALLOWED_FIELDS = frozenset(
    {
        "case_id",
        "duration_ms",
        "event",
        "http_method",
        "model_id",
        "path_template",
        "request_id",
        "state",
        "status_code",
        "workflow_id",
    }
)


def allowlisted_event(
    _logger: object,
    _method_name: str,
    event_dict: Mapping[str, object],
) -> dict[str, object]:
    """Drop every structured field not explicitly classified as safe metadata."""
    return {key: value for key, value in event_dict.items() if key in _ALLOWED_FIELDS}


def configure_logging() -> None:
    """Configure one JSON renderer with allowlisting before serialization."""
    structlog.configure(
        processors=[allowlisted_event, structlog.processors.JSONRenderer(sort_keys=True)],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        cache_logger_on_first_use=True,
    )


def safe_event(event: str, **fields: object) -> dict[str, object]:
    """Build a safe event for tests and call sites that need explicit payload control."""
    return allowlisted_event(None, "info", {"event": event, **fields})
