-- R2M initial PostgreSQL schema. Use via db/migrations/0001_initial.sql.
-- Requires PostgreSQL 15+ and pgcrypto (gen_random_uuid). UTC timestamps.
BEGIN;
CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS organizations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL, kind text NOT NULL CHECK(kind IN ('vendor','customer','internal')), slug text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text NOT NULL UNIQUE, display_name text NOT NULL, is_demo boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS org_memberships (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL REFERENCES organizations(id), user_id uuid NOT NULL REFERENCES users(id), role text NOT NULL CHECK(role IN ('vendor_developer','vendor_release_manager','customer_security','customer_ops','org_admin')), created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(organization_id,user_id,role));
CREATE TABLE IF NOT EXISTS vendor_customer_links (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), vendor_org_id uuid NOT NULL REFERENCES organizations(id), customer_org_id uuid NOT NULL REFERENCES organizations(id), status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')), UNIQUE(vendor_org_id,customer_org_id), CHECK(vendor_org_id <> customer_org_id));
CREATE TABLE IF NOT EXISTS agents (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), vendor_org_id uuid NOT NULL REFERENCES organizations(id), slug text NOT NULL, name text NOT NULL, description text, sdk_version text, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(vendor_org_id,slug));
CREATE TABLE IF NOT EXISTS agent_installations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), agent_id uuid NOT NULL REFERENCES agents(id), customer_org_id uuid NOT NULL REFERENCES organizations(id), environment text NOT NULL CHECK(environment IN ('development','staging','production','demo')), status text NOT NULL DEFAULT 'registered', last_heartbeat_at timestamptz, UNIQUE(agent_id,customer_org_id,environment));
CREATE TABLE IF NOT EXISTS builds (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), agent_id uuid NOT NULL REFERENCES agents(id), version text NOT NULL, source_digest text NOT NULL, artifact_digest text NOT NULL, created_by uuid REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(agent_id,artifact_digest));
CREATE TABLE IF NOT EXISTS deployments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), installation_id uuid NOT NULL REFERENCES agent_installations(id), build_id uuid NOT NULL REFERENCES builds(id), status text NOT NULL CHECK(status IN ('proposed','blocked','eligible','deployed','retired')), deployed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ix_deployments_installation ON deployments(installation_id,created_at DESC);
CREATE TABLE IF NOT EXISTS agent_components (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), installation_id uuid NOT NULL REFERENCES agent_installations(id), component_key text NOT NULL, kind text NOT NULL CHECK(kind IN ('orchestrator','model','tool','memory','storage','compute','gateway')), label text NOT NULL, status text NOT NULL DEFAULT 'unknown', metadata jsonb NOT NULL DEFAULT '{}'::jsonb, last_seen_at timestamptz, UNIQUE(installation_id,component_key));
CREATE TABLE IF NOT EXISTS component_edges (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), installation_id uuid NOT NULL REFERENCES agent_installations(id), source_component_id uuid NOT NULL REFERENCES agent_components(id), target_component_id uuid NOT NULL REFERENCES agent_components(id), edge_kind text NOT NULL DEFAULT 'calls', CHECK(source_component_id <> target_component_id));
CREATE TABLE IF NOT EXISTS policy_revisions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), agent_id uuid NOT NULL REFERENCES agents(id), policy_key text NOT NULL, version text NOT NULL, description text NOT NULL, owner_user_id uuid REFERENCES users(id), artifact_hash text NOT NULL, enforcement_point text NOT NULL, definition_metadata jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(agent_id,policy_key,version,artifact_hash));
CREATE TABLE IF NOT EXISTS policy_submissions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), revision_id uuid NOT NULL REFERENCES policy_revisions(id), installation_id uuid NOT NULL REFERENCES agent_installations(id), submitted_by uuid NOT NULL REFERENCES users(id), status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','withdrawn','revoked')), requested_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz, UNIQUE(revision_id,installation_id));
CREATE TABLE IF NOT EXISTS approval_decisions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), submission_id uuid NOT NULL REFERENCES policy_submissions(id), decided_by uuid NOT NULL REFERENCES users(id), decision text NOT NULL CHECK(decision IN ('approve','reject','revoke')), reason text, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS policy_activations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), submission_id uuid NOT NULL REFERENCES policy_submissions(id), revision_id uuid NOT NULL REFERENCES policy_revisions(id), installation_id uuid NOT NULL REFERENCES agent_installations(id), artifact_hash text NOT NULL, active boolean NOT NULL DEFAULT true, activated_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz, revoked_at timestamptz);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_policy_activation ON policy_activations(installation_id,revision_id) WHERE active=true;
CREATE TABLE IF NOT EXISTS evaluation_suites (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), suite_key text NOT NULL UNIQUE, description text NOT NULL, mandatory boolean NOT NULL DEFAULT true);
CREATE TABLE IF NOT EXISTS evaluation_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), build_id uuid NOT NULL REFERENCES builds(id), suite_id uuid NOT NULL REFERENCES evaluation_suites(id), status text NOT NULL CHECK(status IN ('running','passed','failed','error')), started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, summary jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE TABLE IF NOT EXISTS evaluation_cases (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES evaluation_runs(id), case_key text NOT NULL, mandatory boolean NOT NULL DEFAULT true, status text NOT NULL CHECK(status IN ('passed','failed','error','skipped')), expected jsonb NOT NULL DEFAULT '{}'::jsonb, actual jsonb NOT NULL DEFAULT '{}'::jsonb, trace_id uuid, evidence_hash text, UNIQUE(run_id,case_key));
CREATE TABLE IF NOT EXISTS executions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), deployment_id uuid NOT NULL REFERENCES deployments(id), customer_org_id uuid NOT NULL REFERENCES organizations(id), trace_id uuid NOT NULL UNIQUE, status text NOT NULL CHECK(status IN ('running','completed','failed','cancelled')), started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz, scenario text, metadata jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE INDEX IF NOT EXISTS ix_executions_customer_time ON executions(customer_org_id,started_at DESC);
CREATE TABLE IF NOT EXISTS spans (
 id uuid PRIMARY KEY, execution_id uuid NOT NULL REFERENCES executions(id), parent_span_id uuid REFERENCES spans(id) DEFERRABLE INITIALLY DEFERRED, kind text NOT NULL, name text NOT NULL, status text NOT NULL DEFAULT 'running', started_at timestamptz NOT NULL, ended_at timestamptz, duration_ms numeric(16,3), attributes jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE INDEX IF NOT EXISTS ix_spans_execution ON spans(execution_id,started_at);
CREATE TABLE IF NOT EXISTS execution_events (
 id uuid PRIMARY KEY, execution_id uuid NOT NULL REFERENCES executions(id), span_id uuid REFERENCES spans(id), event_type text NOT NULL, occurred_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(), severity text NOT NULL DEFAULT 'info', status text, attributes jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE INDEX IF NOT EXISTS ix_events_execution_time ON execution_events(execution_id,occurred_at);
CREATE TABLE IF NOT EXISTS tool_actions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), execution_id uuid NOT NULL REFERENCES executions(id), span_id uuid REFERENCES spans(id), tool_key text NOT NULL, arguments_hash text NOT NULL, requested_at timestamptz NOT NULL DEFAULT now(), authorized_at timestamptz, executed_at timestamptz, verified_at timestamptz, outcome text NOT NULL DEFAULT 'requested', result_metadata jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE TABLE IF NOT EXISTS runtime_approvals (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), action_id uuid NOT NULL REFERENCES tool_actions(id), reviewer_id uuid REFERENCES users(id), status text NOT NULL CHECK(status IN ('pending','approved','rejected','expired','consumed')), requested_at timestamptz NOT NULL DEFAULT now(), decided_at timestamptz, expires_at timestamptz, nonce_hash text UNIQUE);
CREATE TABLE IF NOT EXISTS policy_decisions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), execution_id uuid NOT NULL REFERENCES executions(id), action_id uuid NOT NULL REFERENCES tool_actions(id), revision_id uuid REFERENCES policy_revisions(id), decision text NOT NULL CHECK(decision IN ('allow','deny','require_approval')), reason_code text NOT NULL, evaluated_at timestamptz NOT NULL DEFAULT now(), details jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE INDEX IF NOT EXISTS ix_policy_decisions_execution ON policy_decisions(execution_id,evaluated_at);
CREATE TABLE IF NOT EXISTS usage_records (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), execution_id uuid NOT NULL REFERENCES executions(id), span_id uuid REFERENCES spans(id), component_kind text NOT NULL, input_tokens bigint, output_tokens bigint, amount_usd numeric(18,8) NOT NULL DEFAULT 0 CHECK(amount_usd >= 0), cost_source text NOT NULL CHECK(cost_source IN ('observed','estimated','allocated','simulated')), duration_ms numeric(16,3), occurred_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS metric_points (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), installation_id uuid NOT NULL REFERENCES agent_installations(id), execution_id uuid REFERENCES executions(id), component_id uuid REFERENCES agent_components(id), metric_key text NOT NULL, metric_value double precision NOT NULL, unit text NOT NULL, source text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ix_metric_points_time ON metric_points(installation_id,metric_key,occurred_at DESC);
CREATE TABLE IF NOT EXISTS incidents (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), installation_id uuid NOT NULL REFERENCES agent_installations(id), execution_id uuid REFERENCES executions(id), policy_decision_id uuid REFERENCES policy_decisions(id), severity text NOT NULL CHECK(severity IN ('low','medium','high','critical')), status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','investigating','resolved')), category text NOT NULL, description text NOT NULL, detected_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz);
CREATE TABLE IF NOT EXISTS evidence_items (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), installation_id uuid NOT NULL REFERENCES agent_installations(id), execution_id uuid REFERENCES executions(id), evaluation_case_id uuid REFERENCES evaluation_cases(id), policy_revision_id uuid REFERENCES policy_revisions(id), incident_id uuid REFERENCES incidents(id), evidence_type text NOT NULL, body jsonb NOT NULL, sha256 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS simulation_services (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), customer_org_id uuid NOT NULL REFERENCES organizations(id), service_key text NOT NULL, environment text NOT NULL DEFAULT 'production', deployment_version text NOT NULL, previous_version text, replicas integer NOT NULL CHECK(replicas > 0), cpu_pct double precision NOT NULL, memory_pct double precision NOT NULL, error_rate_pct double precision NOT NULL, p95_latency_ms double precision NOT NULL, health_status text NOT NULL, last_transition_at timestamptz NOT NULL DEFAULT now(), UNIQUE(customer_org_id,service_key,environment));
CREATE TABLE IF NOT EXISTS simulation_actions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), service_id uuid NOT NULL REFERENCES simulation_services(id), tool_action_id uuid REFERENCES tool_actions(id), kind text NOT NULL, before_state jsonb NOT NULL, after_state jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS integration_configs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL REFERENCES organizations(id), provider text NOT NULL CHECK(provider IN ('keewano')), enabled boolean NOT NULL DEFAULT false, public_configuration jsonb NOT NULL DEFAULT '{}'::jsonb, last_success_at timestamptz, UNIQUE(organization_id,provider));
CREATE TABLE IF NOT EXISTS integration_outbox (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), integration_id uuid NOT NULL REFERENCES integration_configs(id), source_event_id uuid NOT NULL REFERENCES execution_events(id), payload jsonb NOT NULL, state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','sent','failed','dead')), attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(), last_error_class text, UNIQUE(integration_id,source_event_id));
CREATE TABLE IF NOT EXISTS insight_queries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), installation_id uuid NOT NULL REFERENCES agent_installations(id), execution_id uuid REFERENCES executions(id), provider text NOT NULL, prompt_summary text NOT NULL, provider_request_id text, response_summary jsonb, status text NOT NULL, sample_count integer, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS audit_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_user_id uuid REFERENCES users(id), organization_id uuid REFERENCES organizations(id), action text NOT NULL, target_type text NOT NULL, target_id uuid, recorded_at timestamptz NOT NULL DEFAULT now(), request_id text, details jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_events(organization_id,recorded_at DESC);
INSERT INTO schema_migrations(version) VALUES ('0001_initial') ON CONFLICT DO NOTHING;
COMMIT;
