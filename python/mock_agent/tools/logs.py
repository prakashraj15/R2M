"""read_logs: guarded by DATA-001, and every returned line is redacted.

The synthetic raw log deliberately contains fake identifiers and a fake credential so the
redaction is visible in traces and evals. None of them are real.
"""
from r2m import redact

from ..policy import DATA_001
from ..service_state import SERVICE_KEY

TOOL = "read_logs"


def synthetic_raw_logs(svc: dict, limit: int) -> list[str]:
    v, prev = svc["deployment_version"], svc.get("previous_version") or "n/a"
    lines = [f"INFO  deploy {SERVICE_KEY} {v} rolled out (previous {prev})"]
    if svc["health_status"] == "healthy":
        lines += [f"INFO  {v} request ok p95={svc['p95_latency_ms']}ms" for _ in range(3)]
    else:
        lines += [
            f"ERROR {v} POST /v1/payments 502 upstream ledger timeout customer=jane.doe@example.com",
            f"ERROR {v} POST /v1/payments 500 NullPointer in FeeCalculator card=4111 1111 1111 1111",
            f"WARN  {v} retry storm on ledger-client password=demo-not-a-real-secret",
            f"ERROR {v} POST /v1/refunds 500 NullPointer in FeeCalculator",
            f"WARN  {v} p95={svc['p95_latency_ms']}ms error_rate={svc['error_rate_pct']}%",
        ]
    return lines[:limit]


def register(client, world):
    @client.tool(TOOL, risk="low", policies=[DATA_001], component=TOOL)
    def read_logs(service_key: str = SERVICE_KEY, limit: int = 50, include_raw: bool = False) -> dict:
        svc = world.get_service(service_key)
        lines = synthetic_raw_logs(svc, limit)
        return {"service_key": service_key, "redacted": True, "lines": [redact(line) for line in lines]}

    return read_logs
