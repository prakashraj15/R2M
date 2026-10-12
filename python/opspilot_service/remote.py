"""HTTP-backed world and insights for the agent: the same interface the agent always used, served by R2M's
SDK-authenticated /sim endpoints instead of an in-process bridge."""
import httpx

SERVICE = "payments-api"


class R2MSim:
    def __init__(self, api_url: str, token: str, timeout: float = 60.0):
        self._c = httpx.Client(base_url=api_url.rstrip("/") + "/api/v1", timeout=timeout,
                               headers={"authorization": f"Bearer {token}"})

    def _json(self, method: str, path: str, **kw):
        r = self._c.request(method, path, **kw)
        r.raise_for_status()
        return r.json()

    def context(self, artifact_digest: str | None = None) -> dict:
        """Vendor, customer, environment and services this SDK token is scoped to, plus the build's release status."""
        return self._json("GET", "/sim/context", params={"artifact_digest": artifact_digest} if artifact_digest else None)

    # ---- world (what mock_agent calls) ----
    def get_service(self, service_key: str = SERVICE) -> dict:
        return self._json("GET", f"/sim/services/{service_key}")

    def deployment_history(self, service_key: str = SERVICE) -> list[dict]:
        return self._json("GET", f"/sim/services/{service_key}/history")["actions"]

    def apply_action(self, tool: str, changes: dict, execution_id: str | None, service_key: str = SERVICE) -> dict:
        return self._json("POST", f"/sim/services/{service_key}/actions",
                          json={"tool": tool, "changes": changes, "execution_id": execution_id})

    def reset(self, scenario: str) -> dict:
        return self._json("POST", f"/sim/scenarios/{scenario}/reset")

    # ---- insights (Keewano through R2M; advisory only) ----
    def query(self, question: str) -> dict:
        return self._json("POST", "/sim/insights", json={"question": str(question)[:500]})
