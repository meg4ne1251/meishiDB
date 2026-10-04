"""Reject browser writes from untrusted origins and prevent caching private APIs."""

from urllib.parse import urlsplit

from starlette.responses import JSONResponse


class BrowserSecurityMiddleware:
    def __init__(self, app, trusted_origins: list[str]):
        self.app = app
        self.trusted_origins = set(trusted_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)

        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            headers = dict(scope["headers"])
            origin = headers.get(b"origin")
            referer = headers.get(b"referer")
            if origin is not None:
                trusted = origin.decode("latin-1") in self.trusted_origins
            elif referer is not None:
                try:
                    url = urlsplit(referer.decode("latin-1"))
                    trusted = f"{url.scheme}://{url.netloc}" in self.trusted_origins
                except ValueError:
                    trusted = False
            else:
                # Headerless CLI/scanner clients are supported. Browsers identifying
                # a cross-site request must provide a trusted Origin or Referer.
                trusted = headers.get(b"sec-fetch-site") not in {b"cross-site", b"same-site"}
            if not trusted:
                return await JSONResponse(
                    {"detail": "untrusted request origin"}, status_code=403,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)

        async def private_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    (name, value) for name, value in message["headers"]
                    if name.lower() != b"cache-control"
                ] + [(b"cache-control", b"private, no-store")]
            await send(message)

        await self.app(scope, receive, private_send)
