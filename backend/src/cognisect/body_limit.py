"""Pre-parse request-body limit for the public ASGI boundary."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BODY_BYTES = 32_768
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH"})
_TOO_LARGE_BODY = json.dumps(
    {"detail": "request body too large"}, separators=(",", ":")
).encode()

class RequestBodyLimitMiddleware:
    """Reject oversized mutations before JSON parsing or route dispatch."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        """Wrap one ASGI app with a positive byte limit."""
        if max_bytes <= 0:
            msg = "request body limit must be positive"
            raise ValueError(msg)
        self._app = app
        self._max_bytes = max_bytes

    async def _reject(self, scope: Scope, send: Send) -> None:
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(_TOO_LARGE_BODY)).encode()),
        ]
        path = str(scope.get("path", ""))
        if path.startswith("/v1/respond/"):
            headers.extend(
                [
                    (b"cache-control", b"no-store, private"),
                    (b"referrer-policy", b"no-referrer"),
                ]
            )
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": _TOO_LARGE_BODY})

    async def __call__(  # noqa: C901 - complete chunked-body gate is kept together.
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Buffer one bounded mutation body, reject overflow, then replay it once."""
        if scope.get("type") != "http" or scope.get("method") not in _MUTATION_METHODS:
            await self._app(scope, receive, send)
            return
        raw_headers = scope.get("headers", ())
        content_length = next(
            (value for name, value in raw_headers if name.lower() == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = self._max_bytes + 1
            if declared_length > self._max_bytes:
                await self._reject(scope, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes):
                await self._reject(scope, send)
                return
            body.extend(chunk)
            if len(body) > self._max_bytes:
                await self._reject(scope, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self._app(scope, replay_receive, send)
