"""Container healthcheck: the private API and the public web app. Prints no configuration.

HEALTH_URLS (comma-separated) selects the checks; defaults to the R2M Control Plane container's.
"""
import os
import sys
import urllib.request

DEFAULT = "http://127.0.0.1:8000/api/v1/health/live,http://127.0.0.1:3000/"
for url in os.environ.get("HEALTH_URLS", DEFAULT).split(","):
    try:
        with urllib.request.urlopen(url.strip(), timeout=4) as r:
            if r.status >= 400:
                sys.exit(f"unhealthy: {url} -> {r.status}")
    except Exception as exc:
        sys.exit(f"unhealthy: {url} -> {type(exc).__name__}")
