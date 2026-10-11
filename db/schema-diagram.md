# Schema overview

Migrations: `0001_initial.sql` (from `dev_docs/SCHEMA.sql`), then `0002_grants_and_invariants.sql`. Apply them with `python scripts/init_db.py`, which is idempotent and serialized by an advisory lock.

```mermaid
erDiagram
  organizations ||--o{ org_memberships : has
  users ||--o{ org_memberships : has
  organizations ||--o{ vendor_customer_links : "vendor/customer"
  organizations ||--o{ agents : "vendor owns"
  agents ||--o{ agent_installations : "installed at customer"
  agents ||--o{ builds : has
  agent_installations ||--o{ deployments : has
  builds ||--o{ deployments : "deployed as"
  agent_installations ||--o{ agent_components : topology
  agent_components ||--o{ component_edges : edges
  agents ||--o{ policy_revisions : "code-owned"
  policy_revisions ||--o{ policy_submissions : "submitted for"
  agent_installations ||--o{ policy_submissions : ""
  policy_submissions ||--o{ approval_decisions : ""
  policy_submissions ||--o{ policy_activations : "approved =>"
  builds ||--o{ evaluation_runs : ""
  evaluation_suites ||--o{ evaluation_runs : ""
  evaluation_runs ||--o{ evaluation_cases : ""
  deployments ||--o{ executions : ""
  executions ||--o{ spans : ""
  executions ||--o{ execution_events : ""
  executions ||--o{ tool_actions : ""
  tool_actions ||--o{ policy_decisions : ""
  tool_actions ||--o{ runtime_approvals : ""
  tool_actions ||--o{ action_grants : "single-use"
  executions ||--o{ usage_records : ""
  agent_installations ||--o{ incidents : ""
  agent_installations ||--o{ evidence_items : ""
  simulation_services ||--o{ simulation_actions : ""
  organizations ||--o{ integration_configs : ""
  integration_configs ||--o{ integration_outbox : ""
```

## Lifecycles

- **Policy:** register (hash) → submission `pending` → `approved` (activation row, supersedes the same key) | `rejected` → `revoked` (activation deactivated). A new hash means a new revision and a new approval.
- **Release:** eval runs per build → `releases/evaluate` creates or updates the deployment as `eligible` | `blocked` → `deploy` (re-checks the gate) → `deployed`, and the previous deployment becomes `retired`.
- **Runtime action:** `tool_actions` row per authorize call → `policy_decisions` (one per cited revision) → `runtime_approvals` `pending → approved → consumed` (or `rejected`/`expired`) → `action_grants` issued → consumed by `SimulationWorld.apply_action` → `/actions/{id}/result`. Timestamps are kept separately: `requested_at`, `authorized_at`, `executed_at`, `verified_at`.
- **Ingestion:** `execution_events.id = event_id` (dedup). Executions and spans may start as placeholders (`status='placeholder'`) and are completed by later events.
