"""Request guards that run before routing: CSRF header check and rate limiting."""
import hashlib
import time

from .auth import SESSION_COOKIE

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-r2m-csrf"

# (method, path) overrides, else bucket by caller type. Limits are per minute.
ROUTE_LIMITS = {
    ("POST", "/api/v1/auth/session"): ("login", 60),
    ("POST", "/api/v1/integrations/keewano/query"): ("keewano", 10),
}
BROWSER_LIMIT, SDK_LIMIT, IP_LIMIT = 600, 3000, 3000


def csrf_ok(method: str, headers) -> bool:
    """Cookie-authenticated writes must carry X-R2M-CSRF: 1. Cross-site pages can't set custom headers without a
    CORS preflight, which this API never grants. SDK calls (bearer token, no cookie) are exempt."""
    if method not in UNSAFE or headers.get("authorization", "").lower().startswith("bearer "):
        return True
    return headers.get(CSRF_HEADER) == "1"


def client_ip(request) -> str:
    """The TCP peer. X-Forwarded-For is deliberately ignored: Next.js rewrites pass the client's own value through
    unchanged (verified), so it is attacker-controlled. Behind the proxy every browser shares one peer address, so
    per-IP limits cap the proxy as a whole; per-session and per-token limits are the per-caller controls."""
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Fixed one-minute windows in process memory.

    ponytail: single-process counters, reset on restart; move to Redis/Postgres if the API ever runs >1 replica.
    """

    def __init__(self, clock=time.monotonic):
        self._clock, self._hits = clock, {}

    def hit(self, key: str, limit: int) -> int:
        """Records a hit; returns 0 if allowed, else seconds until the window resets."""
        now = self._clock()
        window = int(now // 60)
        start, count = self._hits.get(key, (window, 0))
        if start != window:
            start, count = window, 0
        if count >= limit:
            return int(60 - now % 60) + 1
        self._hits[key] = (start, count + 1)
        if len(self._hits) > 50_000:  # drop stale windows
            self._hits = {k: v for k, v in self._hits.items() if v[0] == window}
        return 0

    def check(self, request) -> int:
        method, path = request.method, request.url.path
        if not path.startswith("/api/") or path.startswith("/api/v1/health/"):
            return 0
        ip = client_ip(request)
        auth = request.headers.get("authorization", "")
        cookie = request.cookies.get(SESSION_COOKIE)
        if auth.lower().startswith("bearer "):
            caller, limit = "sdk:" + hashlib.sha256(auth.encode()).hexdigest()[:32], SDK_LIMIT
        elif cookie:
            caller, limit = "session:" + hashlib.sha256(cookie.encode()).hexdigest()[:32], BROWSER_LIMIT
        else:
            caller, limit = "ip:" + ip, BROWSER_LIMIT
        bucket, route_limit = ROUTE_LIMITS.get((method, path), (None, None))
        checks = [(f"ip:{ip}", IP_LIMIT), (caller, limit)]  # IP cap stops floods of forged/rotating credentials
        if bucket:
            checks.append((f"{bucket}:{ip if bucket == 'login' else caller}", route_limit))
        return max(self.hit(k, n) for k, n in checks)
