#!/usr/bin/env python3
"""Run one disposable, content-safe 50-way race against the public product."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "security" / "production-stress-report.v1.json"
DEFAULT_BASE_URL = "https://cognisect.vercel.app"
_CONCURRENCY = 50
_HTTP_OK = 200
_HTTP_NO_CONTENT = 204
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409
_PRE_SUBMIT_GETS = 2
_EXPECTED_AUDIT_EVENTS = 7
_MIN_TOKEN_LENGTH = 20
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "owner_secret",
        "learner_token",
        "response_url",
        "observed_work",
        "answer",
        "cookie",
        "workflow_id",
        "case_id",
        "receipt_id",
    }
)


@dataclass(frozen=True, slots=True)
class RaceResult:
    """In-memory winning replay coordinates; never serialize these fields."""

    accepted_count: int
    conflict_count: int
    winning_idempotency_key: str
    winning_receipt_id: str


def validate_live_target(base_url: str, tested_release_sha: str) -> None:
    """Require a public HTTPS origin and one exact lowercase Git SHA."""
    parsed = urlparse(base_url)
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        msg = "production stress requires a bare public HTTPS origin"
        raise ValueError(msg)
    if hostname.casefold() == "localhost":
        msg = "production stress cannot target localhost"
        raise ValueError(msg)
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        msg = "production stress requires a public host"
        raise ValueError(msg)
    if _FULL_SHA.fullmatch(tested_release_sha) is None:
        msg = "production stress requires a full lowercase Git SHA"
        raise ValueError(msg)


async def submit_learner_race(
    post: Callable[[str], Awaitable[httpx.Response]],
    *,
    concurrency: int,
) -> RaceResult:
    """Issue distinct commands concurrently and require one accepted receipt."""
    if concurrency != _CONCURRENCY:
        msg = "production release gate requires exactly 50 submissions"
        raise ValueError(msg)
    prefix = uuid4().hex
    keys = [f"stress-submit-{prefix}-{index:02d}" for index in range(concurrency)]
    responses = await asyncio.gather(*(post(key) for key in keys))
    accepted = [
        (key, response)
        for key, response in zip(keys, responses, strict=True)
        if response.status_code == _HTTP_OK
    ]
    conflicts = [
        response for response in responses if response.status_code == _HTTP_CONFLICT
    ]
    if len(accepted) != 1 or len(conflicts) != concurrency - 1:
        msg = "50-way race did not produce exactly one accepted response"
        raise RuntimeError(msg)
    winning_key, winning_response = accepted[0]
    payload = winning_response.json()
    receipt_id = payload.get("receipt_id") if isinstance(payload, Mapping) else None
    if not isinstance(receipt_id, str) or not receipt_id:
        msg = "accepted response omitted its content-minimal receipt"
        raise RuntimeError(msg)
    return RaceResult(
        accepted_count=1,
        conflict_count=len(conflicts),
        winning_idempotency_key=winning_key,
        winning_receipt_id=receipt_id,
    )


def _expect(response: httpx.Response, status_code: int, step: str) -> None:
    if response.status_code != status_code:
        msg = f"production stress step failed: {step}"
        raise RuntimeError(msg)


def _json_object(response: httpx.Response, step: str) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        msg = f"production stress returned a non-object: {step}"
        raise TypeError(msg)
    return payload


async def run_live_stress(  # noqa: C901, PLR0912, PLR0915 - explicit end-to-end gate.
    *,
    base_url: str,
    tested_release_sha: str,
) -> dict[str, object]:
    """Exercise one disposable public workflow and always attempt owner deletion."""
    validate_live_target(base_url, tested_release_sha)
    origin = base_url.rstrip("/")
    timeout = httpx.Timeout(120.0)
    workflow_id: str | None = None
    deleted = False
    owner = httpx.AsyncClient(base_url=origin, timeout=timeout, follow_redirects=False)
    learner = httpx.AsyncClient(base_url=origin, timeout=timeout, follow_redirects=False)
    try:
        health = await owner.get("/api/backend/health")
        version = await owner.get("/api/backend/version")
        _expect(health, _HTTP_OK, "health")
        _expect(version, _HTTP_OK, "version")
        version_payload = _json_object(version, "version")

        prefix = uuid4().hex
        create_key = f"stress-create-{prefix}"
        case_payload = {
            "source_tier": "educator_authored",
            "problem": {"a": -3, "b": 5},
            "observed_work": "-3 - 5 = 2",
            "deidentified_attestation": False,
        }
        bootstrap = await owner.post(
            "/api/backend/v1/cases",
            headers={"Idempotency-Key": create_key},
            json=case_payload,
        )
        _expect(bootstrap, 428, "owner bootstrap")
        created = await owner.post(
            "/api/backend/v1/cases",
            headers={"Idempotency-Key": create_key},
            json=case_payload,
        )
        _expect(created, 201, "create")
        identifiers = _json_object(created, "create")
        case_id = identifiers.get("case_id")
        raw_workflow_id = identifiers.get("workflow_id")
        if not isinstance(case_id, str) or not isinstance(raw_workflow_id, str):
            msg = "create response omitted aggregate identifiers"
            raise TypeError(msg)
        workflow_id = raw_workflow_id

        analyzed = await owner.post(
            f"/api/backend/v1/cases/{case_id}/analysis",
            headers={"Idempotency-Key": f"stress-analysis-{prefix}"},
            json={"expected_version": 0},
        )
        _expect(analyzed, _HTTP_OK, "analysis")
        analyzed_payload = _json_object(analyzed, "analysis")
        if analyzed_payload.get("state") != "PROBE_READY":
            msg = "analysis did not release a teacher-reviewable probe"
            raise RuntimeError(msg)
        analyzed_version = analyzed_payload.get("version")
        if type(analyzed_version) is not int:
            msg = "analysis response omitted its optimistic version"
            raise RuntimeError(msg)

        approved = await owner.post(
            f"/api/backend/v1/workflows/{workflow_id}/probe-approval",
            headers={"Idempotency-Key": f"stress-approval-{prefix}"},
            json={
                "expected_version": analyzed_version,
                "approved": True,
                "expires_in_seconds": 3600,
            },
        )
        _expect(approved, _HTTP_OK, "probe approval")
        approval_payload = _json_object(approved, "probe approval")
        response_url = approval_payload.get("response_url")
        if not isinstance(response_url, str):
            msg = "approved probe omitted its learner capability URL"
            raise TypeError(msg)
        parsed_response_url = urlparse(response_url)
        if parsed_response_url.netloc != urlparse(origin).netloc:
            msg = "learner capability URL escaped the tested origin"
            raise RuntimeError(msg)
        token = parsed_response_url.path.rsplit("/", 1)[-1]
        if len(token) < _MIN_TOKEN_LENGTH:
            msg = "learner capability was unexpectedly short"
            raise RuntimeError(msg)
        learner_path = f"/api/backend/v1/respond/{token}"

        first_get = await learner.get(learner_path)
        second_get = await learner.get(learner_path)
        _expect(first_get, _HTTP_OK, "first learner GET")
        _expect(second_get, _HTTP_OK, "second learner GET")
        for response in (first_get, second_get):
            if response.headers.get("referrer-policy") != "no-referrer":
                msg = "learner GET omitted Referrer-Policy"
                raise RuntimeError(msg)
            if response.headers.get("cache-control") != "no-store, private":
                msg = "learner GET omitted private no-store caching"
                raise RuntimeError(msg)
        probe = _json_object(first_get, "learner GET")
        problem = probe.get("problem")
        if not isinstance(problem, Mapping):
            msg = "learner probe omitted its signed problem"
            raise TypeError(msg)
        a = problem.get("a")
        b = problem.get("b")
        if type(a) is not int or type(b) is not int:
            msg = "learner probe operands were not strict integers"
            raise TypeError(msg)
        submitted_answer = a - b

        async def post(idempotency_key: str) -> httpx.Response:
            return await learner.post(
                learner_path,
                headers={"Idempotency-Key": idempotency_key},
                json={"answer": submitted_answer},
            )

        race = await submit_learner_race(post, concurrency=_CONCURRENCY)
        exact_replay = await post(race.winning_idempotency_key)
        _expect(exact_replay, _HTTP_OK, "exact learner replay")
        replay_payload = _json_object(exact_replay, "exact learner replay")
        if replay_payload.get("receipt_id") != race.winning_receipt_id:
            msg = "exact learner replay did not return the original receipt"
            raise RuntimeError(msg)

        persisted = await owner.get(f"/api/backend/v1/workflows/{workflow_id}")
        audit = await owner.get(f"/api/backend/v1/workflows/{workflow_id}/audit")
        _expect(persisted, _HTTP_OK, "persisted readback")
        _expect(audit, _HTTP_OK, "audit readback")
        persisted_payload = _json_object(persisted, "persisted readback")
        audit_payload = _json_object(audit, "audit readback")
        if persisted_payload.get("state") != "AWAITING_REVIEW":
            msg = "persisted workflow did not reach teacher review"
            raise RuntimeError(msg)
        evidence = persisted_payload.get("deterministic_evidence")
        if not isinstance(evidence, list) or not evidence:
            msg = "persisted workflow omitted deterministic evidence"
            raise RuntimeError(msg)
        events = audit_payload.get("events")
        if not isinstance(events, list) or len(events) != _EXPECTED_AUDIT_EVENTS:
            msg = "stress workflow audit did not contain seven transitions"
            raise RuntimeError(msg)

        deletion = await owner.delete(
            f"/api/backend/v1/workflows/{workflow_id}",
            headers={"Idempotency-Key": f"stress-delete-{prefix}"},
        )
        _expect(deletion, _HTTP_NO_CONTENT, "deletion")
        deleted = True
        after_delete = await owner.get(f"/api/backend/v1/workflows/{workflow_id}")
        _expect(after_delete, _HTTP_NOT_FOUND, "post-deletion read")
        return {
            "schema_version": "cognisect.production-stress-report.v1",
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "base_origin": origin,
            "tested_release_sha": tested_release_sha,
            "provider_sha_verified": True,
            "health_status": health.status_code,
            "served_version": version_payload.get("version"),
            "concurrent_submissions": _CONCURRENCY,
            "accepted_submissions": race.accepted_count,
            "conflicting_submissions": race.conflict_count,
            "pre_submit_gets": _PRE_SUBMIT_GETS,
            "exact_replay_status": exact_replay.status_code,
            "persisted_state": persisted_payload.get("state"),
            "deterministic_evidence_present": True,
            "audit_event_count": len(events),
            "deletion_status": deletion.status_code,
            "post_deletion_read_status": after_delete.status_code,
            "educational_record_deleted": True,
        }
    finally:
        if workflow_id is not None and not deleted:
            with suppress(httpx.HTTPError):
                await owner.delete(
                    f"/api/backend/v1/workflows/{workflow_id}",
                    headers={"Idempotency-Key": f"stress-cleanup-{uuid4().hex}"},
                )
        await learner.aclose()
        await owner.aclose()


def expected_report_shape(*, tested_release_sha: str) -> dict[str, object]:
    """Return a valid content-free shape for validator tests."""
    return {
        "schema_version": "cognisect.production-stress-report.v1",
        "generated_at": "2026-07-17T00:00:00+00:00",
        "base_origin": DEFAULT_BASE_URL,
        "tested_release_sha": tested_release_sha,
        "provider_sha_verified": True,
        "health_status": _HTTP_OK,
        "served_version": "0.1.0",
        "concurrent_submissions": _CONCURRENCY,
        "accepted_submissions": 1,
        "conflicting_submissions": _CONCURRENCY - 1,
        "pre_submit_gets": _PRE_SUBMIT_GETS,
        "exact_replay_status": _HTTP_OK,
        "persisted_state": "AWAITING_REVIEW",
        "deterministic_evidence_present": True,
        "audit_event_count": _EXPECTED_AUDIT_EVENTS,
        "deletion_status": _HTTP_NO_CONTENT,
        "post_deletion_read_status": _HTTP_NOT_FOUND,
        "educational_record_deleted": True,
    }


def _contains_forbidden_content(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in _FORBIDDEN_REPORT_KEYS or _contains_forbidden_content(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_content(item) for item in value)
    return False


def validate_stress_report(path: Path) -> bool:
    """Require every release-gate invariant and no persisted capability/content."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            return False
        validate_live_target(
            str(report.get("base_origin", "")),
            str(report.get("tested_release_sha", "")),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return bool(
        report.get("schema_version") == "cognisect.production-stress-report.v1"
        and report.get("provider_sha_verified") is True
        and report.get("health_status") == _HTTP_OK
        and report.get("concurrent_submissions") == _CONCURRENCY
        and report.get("accepted_submissions") == 1
        and report.get("conflicting_submissions") == _CONCURRENCY - 1
        and report.get("pre_submit_gets") == _PRE_SUBMIT_GETS
        and report.get("exact_replay_status") == _HTTP_OK
        and report.get("persisted_state") == "AWAITING_REVIEW"
        and report.get("deterministic_evidence_present") is True
        and report.get("audit_event_count") == _EXPECTED_AUDIT_EVENTS
        and report.get("deletion_status") == _HTTP_NO_CONTENT
        and report.get("post_deletion_read_status") == _HTTP_NOT_FOUND
        and report.get("educational_record_deleted") is True
        and not _contains_forbidden_content(report)
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--provider-sha-verified", action="store_true")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tested-release-sha")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run only with explicit live/SHA authority, or verify a checked report."""
    args = _parser().parse_args(argv)
    if args.check:
        valid = validate_stress_report(args.output)
        print("production stress report verified" if valid else "stress report verification FAILED")
        return 0 if valid else 1
    if not args.live or not args.provider_sha_verified or args.tested_release_sha is None:
        print("NOT RUN — pass --live, --provider-sha-verified, and the exact release SHA")
        return 0
    try:
        validate_live_target(args.base_url, args.tested_release_sha)
        report = asyncio.run(
            run_live_stress(
                base_url=args.base_url,
                tested_release_sha=args.tested_release_sha,
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if not validate_stress_report(args.output):
            args.output.unlink(missing_ok=True)
            print("FAILED — stress report did not pass content-safe validation")
            return 1
    except Exception:  # noqa: BLE001 - live failures must not leak content or capabilities.
        args.output.unlink(missing_ok=True)
        print("FAILED — production stress gate did not produce a report")
        return 1
    print("PASSED — production stress report written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
