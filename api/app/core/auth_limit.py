"""Bound authentication requests per peer for the single-process deployment."""

import math
from time import monotonic

from starlette.responses import JSONResponse


class AuthRateLimitMiddleware:
    PATHS = {
        "/api/auth/register", "/api/auth/login",
        "/api/webauthn/login/begin", "/api/webauthn/login/finish",
    }

    def __init__(self, app, max_requests: int = 20, window_seconds: int = 60, max_peers: int = 4096):
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_peers = max_peers
        self.attempts: dict[tuple[str, str], tuple[int, float]] = {}
        self.next_cleanup = 0.0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"].rstrip("/") not in self.PATHS:
            return await self.app(scope, receive, send)
        now = monotonic()
        if now >= self.next_cleanup:
            self.attempts = {key: value for key, value in self.attempts.items() if value[1] > now}
            self.next_cleanup = now + self.window_seconds
        peer = scope.get("client") or ("unknown", 0)
        key = (peer[0], scope["path"].rstrip("/"))
        count, reset_at = self.attempts.get(key, (0, now + self.window_seconds))
        if reset_at <= now:
            count, reset_at = 0, now + self.window_seconds
        if count >= self.max_requests or (key not in self.attempts and len(self.attempts) >= self.max_peers):
            return await JSONResponse(
                {"detail": "too many authentication requests; retry later"}, status_code=429,
                headers={"Retry-After": str(max(1, math.ceil(reset_at - now)))},
            )(scope, receive, send)
        self.attempts[key] = (count + 1, reset_at)
        await self.app(scope, receive, send)
