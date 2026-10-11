"""Container healthcheck: private FastAPI liveness and public Next page. Prints no configuration."""
import sys
import urllib.request

CHECKS = ("http://127.0.0.1:8000/api/v1/health/live", "http://127.0.0.1:3000/")

for url in CHECKS:
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            if r.status >= 400:
                sys.exit(f"unhealthy: {url} -> {r.status}")
    except Exception as exc:
        sys.exit(f"unhealthy: {url} -> {type(exc).__name__}")
