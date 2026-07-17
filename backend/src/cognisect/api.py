"""Exact public FastAPI surface for the teacher-controlled workflow."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware.base import RequestResponseEndpoint
from starlette.routing import Route

from cognisect import __version__
from cognisect.api_models import (
    AnalysisRequest,
    AuditEventResponse,
    AuditResponse,
    CreateCaseRequest,
    CreateCaseResponse,
    EvidenceReceiptResponse,
    LearnerProbeResponse,
    LearnerReceiptResponse,
    LearnerSubmitRequest,
    LearnerTokenResponse,
    OwnerBootstrapResponse,
    ProbeApprovalRequest,
    ReviewRequest,
    VersionResponse,
    WorkflowResponse,
)
from cognisect.body_limit import RequestBodyLimitMiddleware
from cognisect.config import Settings, is_production
from cognisect.database import create_engine, create_session_factory
from cognisect.db_models import SCHEMA_VERSION
from cognisect.interpreter import COMPILER_VERSION, REGISTRY_VERSION
from cognisect.model_analyzer import ResponsesAnalyzer
from cognisect.model_attempts import ATTEMPT_GRACE_SECONDS, PostgresAttemptJournal
from cognisect.rate_limit import (
    InvalidProxyIdentityError,
    PostgresRateLimiter,
    RateLimitDecision,
    case_creation_key_material,
)
from cognisect.repositories import (
    ConcurrentWriteError,
    OwnedResourceNotFoundError,
    PersistenceError,
)
from cognisect.safe_logging import configure_logging
from cognisect.services import (
    Analyzer,
    AnalyzerExecutionError,
    AnalyzerNotConfiguredError,
    ExpiredLearnerTokenError,
    GraphRuntime,
    LearnerTokenNotFoundError,
    ReplayConflictError,
    RetentionService,
    WorkflowService,
)
from cognisect.workflow import WorkflowTransitionError
from cognisect.workflow_graph import (
    WorkflowGraphRuntime,
    checkpoint_connection_url,
    secure_checkpoint_serializer,
)

OWNER_COOKIE_NAME = "cognisect_owner"
IDEMPOTENCY_KEY_MIN_LENGTH = 8
IDEMPOTENCY_KEY_MAX_LENGTH = 200
VISIBLE_ASCII_MIN = 0x21
VISIBLE_ASCII_MAX = 0x7E
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=200,
        pattern=r"^[\x21-\x7e]+$",
    ),
]
OwnerCookie = Annotated[str | None, Cookie(alias=OWNER_COOKIE_NAME)]
OWNER_SECRET_PATTERN = re.compile(r"^(?:[A-Za-z0-9_-]{43}|[0-9a-f]{64})$")
EXPECTED_ALEMBIC_HEAD = "c5d7e9f1a204"
RATE_LIMIT_WINDOW_SECONDS = 3_600
RATE_LIMIT_RESPONSE = {
    "description": "Fixed-window request quota exceeded",
    "headers": {
        "Retry-After": {
            "description": "Seconds until the current quota window expires",
            "schema": {"type": "integer", "minimum": 1},
        }
    },
}


def _owner_or_404(owner_secret: str | None) -> str:
    if owner_secret is None or OWNER_SECRET_PATTERN.fullmatch(owner_secret) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    return owner_secret


def _privacy_headers(response: Response) -> None:
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store, private"


def _requires_privacy_headers(path: str) -> bool:
    return path.startswith("/v1/respond/") or (
        path.startswith("/v1/workflows/") and path.endswith("/receipt")
    )


def _raise_if_limited(decision: RateLimitDecision) -> None:
    if decision.allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="rate limit exceeded",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def create_app(  # noqa: C901, PLR0915
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    analyzer: Analyzer | None,
    graph_runtime: GraphRuntime | None = None,
    _owned_engine: AsyncEngine | None = None,
) -> FastAPI:
    """Construct an app; analyzer omission remains explicit and never installs a fake."""
    resolved_settings = settings or Settings()  # type: ignore[call-arg]
    owned_engine = _owned_engine
    if session_factory is None:
        owned_engine = create_engine(resolved_settings.database_url)
        session_factory = create_session_factory(owned_engine)

    configure_logging()
    logger = structlog.get_logger()
    service = WorkflowService(
        session_factory,
        resolved_settings,
        analyzer=analyzer,
    )
    if graph_runtime is not None:
        service.attach_graph_runtime(graph_runtime)
    rate_limiter = PostgresRateLimiter(
        session_factory,
        abuse_key_pepper=resolved_settings.abuse_key_pepper,
    )

    async def retention_loop(retention: RetentionService) -> None:
        while True:
            try:
                purged_cases = await retention.purge_expired()
                logger.info(
                    "retention_iteration_complete",
                    purged_cases=purged_cases,
                )
            except Exception:
                logger.exception("retention_iteration_failed")
            await asyncio.sleep(resolved_settings.retention_interval_seconds)

    @asynccontextmanager
    async def production_runtime(
        _app: FastAPI, active_graph_runtime: GraphRuntime | None
    ) -> AsyncIterator[None]:
        task: asyncio.Task[None] | None = None
        if is_production(resolved_settings):
            retention = RetentionService(
                session_factory,
                retention_days=resolved_settings.retention_days,
                graph_runtime=active_graph_runtime,
                rate_limiter=rate_limiter,
            )
            task = asyncio.create_task(
                retention_loop(retention),
                name="cognisect-production-retention",
            )
            _app.state.retention_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            if graph_runtime is None and is_production(resolved_settings):
                async with AsyncPostgresSaver.from_conn_string(
                    checkpoint_connection_url(resolved_settings.database_url),
                    serde=secure_checkpoint_serializer(),
                ) as managed_checkpointer:
                    managed_runtime = WorkflowGraphRuntime(
                        session_factory,
                        managed_checkpointer,
                        update_action=service.advance_response_update,
                    )
                    service.attach_graph_runtime(managed_runtime)
                    _app.state.graph_runtime = managed_runtime
                    async with production_runtime(_app, managed_runtime):
                        yield
            else:
                async with production_runtime(_app, graph_runtime):
                    yield
        finally:
            if owned_engine is not None:
                await owned_engine.dispose()

    app = FastAPI(
        title="COGNISECT API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestBodyLimitMiddleware)
    app.state.settings = resolved_settings
    app.state.session_factory = session_factory
    app.state.workflow_service = service
    app.state.graph_runtime = graph_runtime
    app.state.rate_limiter = rate_limiter
    app.state.retention_task = None

    @app.middleware("http")
    async def structured_request_log(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if _requires_privacy_headers(request.url.path):
            _privacy_headers(response)
        route = request.scope.get("route")
        logger.info(
            "http_request",
            http_method=request.method,
            path_template=route.path if isinstance(route, Route) else "unmatched",
            status_code=response.status_code,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        validation_errors = exception.errors()
        invalid_learner_body = (
            request.method == "POST"
            and request.url.path.startswith("/v1/respond/")
            and bool(validation_errors)
            and all(
                tuple(error.get("loc", ()))[:2] == ("body", "answer")
                for error in validation_errors
            )
        )
        idempotency_key = request.headers.get("Idempotency-Key")
        token = request.path_params.get("token")
        if (
            invalid_learner_body
            and isinstance(token, str)
            and isinstance(idempotency_key, str)
            and IDEMPOTENCY_KEY_MIN_LENGTH
            <= len(idempotency_key)
            <= IDEMPOTENCY_KEY_MAX_LENGTH
            and all(
                VISIBLE_ASCII_MIN <= ord(character) <= VISIBLE_ASCII_MAX
                for character in idempotency_key
            )
        ):
            try:
                receipt = await service.submit_invalid_learner_answer(
                    token=token,
                    idempotency_key=idempotency_key,
                )
            except (OwnedResourceNotFoundError, LearnerTokenNotFoundError):
                return JSONResponse(status_code=404, content={"detail": "resource not found"})
            except ExpiredLearnerTokenError:
                return JSONResponse(status_code=410, content={"detail": "learner link expired"})
            except (ReplayConflictError, ConcurrentWriteError, WorkflowTransitionError):
                return JSONResponse(status_code=409, content={"detail": "command conflict"})
            content = LearnerReceiptResponse(
                receipt_id=receipt.receipt_id,
                accepted_at=receipt.accepted_at,
            ).model_dump(mode="json")
            return JSONResponse(status_code=200, content=content)
        safe_errors = [
            {key: value for key, value in error.items() if key not in {"input", "ctx"}}
            for error in validation_errors
        ]
        return JSONResponse(status_code=422, content={"detail": safe_errors})

    @app.exception_handler(OwnedResourceNotFoundError)
    @app.exception_handler(LearnerTokenNotFoundError)
    async def not_found_handler(_request: Request, _exception: PersistenceError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "resource not found"})

    @app.exception_handler(ExpiredLearnerTokenError)
    async def gone_handler(_request: Request, _exception: ExpiredLearnerTokenError) -> JSONResponse:
        return JSONResponse(status_code=410, content={"detail": "learner link expired"})

    @app.exception_handler(ReplayConflictError)
    @app.exception_handler(ConcurrentWriteError)
    @app.exception_handler(WorkflowTransitionError)
    async def conflict_handler(_request: Request, _exception: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "command conflict"})

    @app.exception_handler(AnalyzerNotConfiguredError)
    async def analyzer_unavailable_handler(
        _request: Request, _exception: AnalyzerNotConfiguredError
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "analysis unavailable"})

    @app.exception_handler(AnalyzerExecutionError)
    async def analyzer_failure_handler(
        _request: Request, _exception: AnalyzerExecutionError
    ) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": "analysis failed"})

    @app.post(
        "/v1/cases",
        response_model=CreateCaseResponse,
        status_code=201,
        responses={
            status.HTTP_428_PRECONDITION_REQUIRED: {
                "model": OwnerBootstrapResponse,
                "description": "Owner session initialized before educational mutation",
            },
            status.HTTP_429_TOO_MANY_REQUESTS: RATE_LIMIT_RESPONSE,
        },
    )
    async def create_case_route(
        http_request: Request,
        request: CreateCaseRequest,
        idempotency_key: IdempotencyKey,
        owner_secret: OwnerCookie = None,
    ) -> Response:
        client_host = http_request.client.host if http_request.client is not None else "unknown"
        try:
            key_material = case_creation_key_material(
                http_request.headers,
                method=http_request.method,
                path=http_request.url.path,
                client_host=client_host,
                proxy_signing_secret=resolved_settings.proxy_signing_secret,
            )
        except InvalidProxyIdentityError as exception:
            raise HTTPException(status_code=400, detail="invalid proxy identity") from exception
        _raise_if_limited(
            await rate_limiter.consume(
                scope="case_creation",
                key_material=key_material,
                limit=resolved_settings.case_creation_limit_per_hour,
                window_seconds=RATE_LIMIT_WINDOW_SECONDS,
            )
        )
        if owner_secret is None or OWNER_SECRET_PATTERN.fullmatch(owner_secret) is None:
            bootstrapped_secret = await service.bootstrap_owner()
            bootstrap_response = JSONResponse(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                content=OwnerBootstrapResponse().model_dump(mode="json"),
            )
            _privacy_headers(bootstrap_response)
            bootstrap_response.set_cookie(
                key=OWNER_COOKIE_NAME,
                value=bootstrapped_secret,
                secure=is_production(resolved_settings),
                httponly=True,
                samesite="lax",
                max_age=resolved_settings.retention_days * 86_400,
                path="/",
            )
            return bootstrap_response
        created = await service.create_case(
            request,
            idempotency_key=idempotency_key,
            owner_secret=owner_secret,
        )
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=CreateCaseResponse(
                case_id=created.case_id,
                workflow_id=created.workflow_id,
            ).model_dump(mode="json"),
        )

    @app.post(
        "/v1/cases/{case_id}/analysis",
        response_model=WorkflowResponse,
        responses={status.HTTP_429_TOO_MANY_REQUESTS: RATE_LIMIT_RESPONSE},
    )
    async def analyze_case_route(
        case_id: UUID,
        request: AnalysisRequest,
        idempotency_key: IdempotencyKey,
        owner_secret: OwnerCookie = None,
    ) -> WorkflowResponse:
        secret = _owner_or_404(owner_secret)
        await service.authorize_owner_capability(secret)
        _raise_if_limited(
            await rate_limiter.consume(
                scope="analysis",
                key_material=secret,
                limit=resolved_settings.analysis_limit_per_hour,
                window_seconds=RATE_LIMIT_WINDOW_SECONDS,
            )
        )
        workflow = await service.analyze_case(
            owner_secret=secret,
            case_id=case_id,
            expected_version=request.expected_version,
            idempotency_key=idempotency_key,
        )
        return await service.get_workflow_dto(secret, workflow.id)

    @app.get("/v1/workflows/{workflow_id}", response_model=WorkflowResponse)
    async def get_workflow_route(
        workflow_id: UUID,
        response: Response,
        owner_secret: OwnerCookie = None,
    ) -> WorkflowResponse:
        workflow = await service.get_workflow_dto(
            _owner_or_404(owner_secret), workflow_id
        )
        _privacy_headers(response)
        return workflow

    @app.post(
        "/v1/workflows/{workflow_id}/probe-approval", response_model=LearnerTokenResponse
    )
    async def approve_probe_route(
        workflow_id: UUID,
        request: ProbeApprovalRequest,
        response: Response,
        idempotency_key: IdempotencyKey,
        owner_secret: OwnerCookie = None,
    ) -> LearnerTokenResponse:
        secret = _owner_or_404(owner_secret)
        approved = await service.approve_probe(
            owner_secret=secret,
            workflow_id=workflow_id,
            request=request,
            idempotency_key=idempotency_key,
        )
        _privacy_headers(response)
        workflow = await service.get_workflow_dto(secret, workflow_id)
        return LearnerTokenResponse(
            response_url=(
                f"{resolved_settings.public_app_url}/respond/{approved.token}"
                if approved.token is not None
                else None
            ),
            expires_at=approved.expires_at,
            workflow=workflow,
        )

    @app.get("/v1/respond/{token}", response_model=LearnerProbeResponse)
    async def get_learner_probe_route(token: str) -> LearnerProbeResponse:
        return await service.get_learner_probe(token)

    @app.post("/v1/respond/{token}", response_model=LearnerReceiptResponse)
    async def submit_learner_route(
        token: str,
        request: LearnerSubmitRequest,
        idempotency_key: IdempotencyKey,
    ) -> LearnerReceiptResponse:
        receipt = await service.submit_learner_response(
            token=token,
            request=request,
            idempotency_key=idempotency_key,
        )
        return LearnerReceiptResponse(
            receipt_id=receipt.receipt_id, accepted_at=receipt.accepted_at
        )

    @app.post("/v1/workflows/{workflow_id}/review", response_model=WorkflowResponse)
    async def review_workflow_route(
        workflow_id: UUID,
        request: ReviewRequest,
        idempotency_key: IdempotencyKey,
        owner_secret: OwnerCookie = None,
    ) -> WorkflowResponse:
        secret = _owner_or_404(owner_secret)
        await service.review_workflow(
            owner_secret=secret,
            workflow_id=workflow_id,
            request=request,
            idempotency_key=idempotency_key,
        )
        return await service.get_workflow_dto(secret, workflow_id)

    @app.get("/v1/workflows/{workflow_id}/audit", response_model=AuditResponse)
    async def audit_route(
        workflow_id: UUID, owner_secret: OwnerCookie = None
    ) -> AuditResponse:
        events = await service.get_audit(_owner_or_404(owner_secret), workflow_id)
        return AuditResponse(
            workflow_id=workflow_id,
            events=[
                AuditEventResponse(
                    sequence=event.sequence,
                    from_state=event.from_state.value if event.from_state is not None else None,
                    to_state=event.to_state.value,
                    version=event.version,
                    occurred_at=event.occurred_at,
                )
                for event in events
            ],
        )

    @app.get(
        "/v1/workflows/{workflow_id}/receipt",
        response_model=EvidenceReceiptResponse,
    )
    async def receipt_route(
        workflow_id: UUID,
        response: Response,
        owner_secret: OwnerCookie = None,
    ) -> EvidenceReceiptResponse:
        receipt = await service.get_evidence_receipt(_owner_or_404(owner_secret), workflow_id)
        _privacy_headers(response)
        response.headers["Content-Disposition"] = (
            f'attachment; filename="cognisect-evidence-{workflow_id}.json"'
        )
        return receipt

    @app.delete("/v1/workflows/{workflow_id}", status_code=204)
    async def delete_workflow_route(
        workflow_id: UUID,
        idempotency_key: IdempotencyKey,
        owner_secret: OwnerCookie = None,
    ) -> Response:
        await service.delete_workflow(
            owner_secret=_owner_or_404(owner_secret),
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
        )
        return Response(status_code=204)

    @app.get("/health")
    async def health_route() -> dict[str, str]:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get(
        "/ready",
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Not ready"}},
    )
    async def ready_route() -> dict[str, str]:
        try:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
                revisions = list(
                    (
                        await session.scalars(
                            text("SELECT version_num FROM alembic_version")
                        )
                    ).all()
                )
        except Exception as exception:
            raise HTTPException(status_code=503, detail="not ready") from exception
        if revisions != [EXPECTED_ALEMBIC_HEAD]:
            raise HTTPException(status_code=503, detail="not ready")
        return {"status": "ready"}

    @app.get("/version", response_model=VersionResponse)
    async def version_route() -> VersionResponse:
        return VersionResponse(
            version=__version__,
            schema_version=SCHEMA_VERSION,
            registry_version=REGISTRY_VERSION,
            compiler_version=COMPILER_VERSION,
            source_revision=resolved_settings.source_revision,
        )

    return app


def build_app() -> FastAPI:
    """Install the real analyzer only for a fully validated production environment."""
    settings = Settings()  # type: ignore[call-arg]
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    analyzer = (
        ResponsesAnalyzer(
            settings,
            journal=PostgresAttemptJournal(
                sessions,
                active_window_seconds=(
                    settings.model_timeout_seconds + ATTEMPT_GRACE_SECONDS
                ),
            ),
        )
        if is_production(settings)
        else None
    )
    return create_app(
        settings=settings,
        session_factory=sessions,
        analyzer=analyzer,
        _owned_engine=engine,
    )
