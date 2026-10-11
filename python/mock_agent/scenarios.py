"""The four showcase scenarios (spec §7.3). The platform owns their baseline world state."""
from __future__ import annotations

SCENARIOS = {
    "healthy": {
        "title": "Healthy observation",
        "description": "Read health and history and reply without changing anything.",
        "suggested_prompts": ["How is payments-api doing?", "Check status"],
    },
    "degraded": {
        "title": "Degraded payments-api",
        "description": "Diagnose post-deploy errors; ask Keewano which remediation historically worked; "
                       "fall back to a safe deterministic step when intelligence is unavailable.",
        "suggested_prompts": ["payments-api is throwing errors, fix it", "What should we do?"],
    },
    "approval": {
        "title": "Approval-required rollback",
        "description": "Rollback is gated by DEPLOY-001: approve the exact action in R2M, then say 'continue'.",
        "suggested_prompts": ["Roll back payments-api to v2.0", "continue"],
    },
    "faulty": {
        "title": "Faulty build (fault injection)",
        "description": "Vendor-only: run the faulty-1.0 variant's ungated rollback route. The simulated "
                       "infrastructure refuses it and R2M opens a critical incident.",
        "suggested_prompts": ["Run the faulty build rollback"],
    },
}

# Only the vendor can trigger the fault-injection path; customers never get the bypass toggle.
FAULT_INJECTION_ROLES = frozenset({"vendor_developer", "vendor_release_manager"})


def suggestions(scenario: str) -> list[str]:
    return list(SCENARIOS.get(scenario, {}).get("suggested_prompts", []))
