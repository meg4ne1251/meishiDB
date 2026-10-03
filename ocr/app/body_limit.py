"""Bound request bodies before multipart parsing, including chunked transfers."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

MAX_BODY_BYTES = 16 * 1024 * 1024  # image limit plus multipart overhead


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes=MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        if length > self.max_bytes:
            return await JSONResponse(
                {"detail": "request body too large"}, status_code=413
            )(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(
                        status_code=413, detail="request body too large"
                    )
            return message

        await self.app(scope, limited_receive, send)
