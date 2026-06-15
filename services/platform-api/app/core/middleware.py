import time
from collections import defaultdict, deque
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 300):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def limit_for(self, path: str) -> int:
        if path in {"/api/auth/login", "/api/auth/register"}:
            return 20
        if path == "/api/agent/register":
            return 10
        if path.endswith("/logs") and "/resources/" in path:
            return 30
        if "/resources" in path:
            return 120
        if path.startswith("/api/ingest/"):
            return self.requests_per_minute
        return self.requests_per_minute

    async def dispatch(self, request: Request, call_next):
        key = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown").split(",")[0]
        path = request.url.path
        limit = self.limit_for(path)
        now = time.time()
        window = self.hits[f"{key}:{path}"]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        window.append(now)
        return await call_next(request)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
