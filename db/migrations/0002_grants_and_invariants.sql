-- R2M 0002: single-use action grants, reviewer-visible action arguments, and the
-- cross-table invariants BUILD_NOTES.md says simple FKs cannot express.
BEGIN;

ALTER TABLE tool_actions ADD COLUMN IF NOT EXISTS arguments jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE simulation_actions ADD COLUMN IF NOT EXISTS authorized boolean NOT NULL DEFAULT false;

-- Short-lived, single-use, HMAC-signed grant bound to org, deployment, policy revisions, tool,
-- canonical argument hash and execution. Only sha256(nonce) is stored. applied_at marks use at the
-- simulated infrastructure boundary; consumed_at marks the SDK's executed-result report.
CREATE TABLE IF NOT EXISTS action_grants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 action_id uuid NOT NULL REFERENCES tool_actions(id),
 customer_org_id uuid NOT NULL REFERENCES organizations(id),
 deployment_id uuid NOT NULL REFERENCES deployments(id),
 execution_id uuid NOT NULL REFERENCES executions(id),
 policy_revision_ids uuid[] NOT NULL DEFAULT '{}',
 tool_key text NOT NULL,
 arguments_hash text NOT NULL,
 nonce_hash text NOT NULL UNIQUE,
 issued_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 applied_at timestamptz,
 consumed_at timestamptz,
 CHECK (expires_at > issued_at));

CREATE INDEX IF NOT EXISTS ix_tool_actions_execution ON tool_actions(execution_id, requested_at);
CREATE INDEX IF NOT EXISTS ix_incidents_installation ON incidents(installation_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_evidence_installation ON evidence_items(installation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_usage_execution ON usage_records(execution_id);
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON integration_outbox(state, next_attempt_at);

-- Policy submission: revision must belong to the installed agent.
CREATE OR REPLACE FUNCTION r2m_check_submission() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM policy_revisions r JOIN agent_installations i ON i.agent_id = r.agent_id
                 WHERE r.id = NEW.revision_id AND i.id = NEW.installation_id) THEN
    RAISE EXCEPTION 'policy revision agent does not match installation agent' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_check_submission ON policy_submissions;
CREATE TRIGGER trg_check_submission BEFORE INSERT OR UPDATE ON policy_submissions FOR EACH ROW EXECUTE FUNCTION r2m_check_submission();

-- Approval decision: author cannot decide, decider must be customer security in the installation's org.
CREATE OR REPLACE FUNCTION r2m_check_approval_decision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM policy_submissions s WHERE s.id = NEW.submission_id AND s.submitted_by = NEW.decided_by) THEN
    RAISE EXCEPTION 'submitter cannot decide their own policy submission' USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM policy_submissions s JOIN agent_installations i ON i.id = s.installation_id
                 JOIN org_memberships m ON m.organization_id = i.customer_org_id
                 WHERE s.id = NEW.submission_id AND m.user_id = NEW.decided_by AND m.role = 'customer_security') THEN
    RAISE EXCEPTION 'decider lacks customer_security in the installation organization' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_check_approval_decision ON approval_decisions;
CREATE TRIGGER trg_check_approval_decision BEFORE INSERT ON approval_decisions FOR EACH ROW EXECUTE FUNCTION r2m_check_approval_decision();

-- Activation must mirror its approved submission and the revision's hash.
CREATE OR REPLACE FUNCTION r2m_check_activation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM policy_submissions s JOIN policy_revisions r ON r.id = s.revision_id
                 WHERE s.id = NEW.submission_id AND s.revision_id = NEW.revision_id
                   AND s.installation_id = NEW.installation_id AND r.artifact_hash = NEW.artifact_hash
                   AND (s.status = 'approved' OR NOT NEW.active)) THEN
    RAISE EXCEPTION 'activation does not match an approved submission' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_check_activation ON policy_activations;
CREATE TRIGGER trg_check_activation BEFORE INSERT OR UPDATE ON policy_activations FOR EACH ROW EXECUTE FUNCTION r2m_check_activation();

-- Deployment build must be a build of the installed agent.
CREATE OR REPLACE FUNCTION r2m_check_deployment() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM builds b JOIN agent_installations i ON i.agent_id = b.agent_id
                 WHERE b.id = NEW.build_id AND i.id = NEW.installation_id) THEN
    RAISE EXCEPTION 'deployment build agent does not match installation agent' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_check_deployment ON deployments;
CREATE TRIGGER trg_check_deployment BEFORE INSERT OR UPDATE ON deployments FOR EACH ROW EXECUTE FUNCTION r2m_check_deployment();

-- Topology edges must connect components of the same installation.
CREATE OR REPLACE FUNCTION r2m_check_edge() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT count(*) FROM agent_components c WHERE c.installation_id = NEW.installation_id
        AND c.id IN (NEW.source_component_id, NEW.target_component_id)) <> 2 THEN
    RAISE EXCEPTION 'edge components must belong to the edge installation' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_check_edge ON component_edges;
CREATE TRIGGER trg_check_edge BEFORE INSERT OR UPDATE ON component_edges FOR EACH ROW EXECUTE FUNCTION r2m_check_edge();

-- Runtime approval reviewer must be customer security in the action's customer org.
CREATE OR REPLACE FUNCTION r2m_check_runtime_approval() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.reviewer_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM tool_actions a JOIN executions e ON e.id = a.execution_id
       JOIN org_memberships m ON m.organization_id = e.customer_org_id
       WHERE a.id = NEW.action_id AND m.user_id = NEW.reviewer_id AND m.role = 'customer_security') THEN
    RAISE EXCEPTION 'runtime approval reviewer lacks customer_security in the action organization' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_check_runtime_approval ON runtime_approvals;
CREATE TRIGGER trg_check_runtime_approval BEFORE INSERT OR UPDATE ON runtime_approvals FOR EACH ROW EXECUTE FUNCTION r2m_check_runtime_approval();

-- Audit events and evidence are append-only (application-level guarantee, not WORM storage).
CREATE OR REPLACE FUNCTION r2m_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;
DROP TRIGGER IF EXISTS trg_audit_append_only ON audit_events;
CREATE TRIGGER trg_audit_append_only BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION r2m_append_only();
DROP TRIGGER IF EXISTS trg_evidence_append_only ON evidence_items;
CREATE TRIGGER trg_evidence_append_only BEFORE UPDATE OR DELETE ON evidence_items FOR EACH ROW EXECUTE FUNCTION r2m_append_only();

INSERT INTO schema_migrations(version) VALUES ('0002_grants_and_invariants') ON CONFLICT DO NOTHING;
COMMIT;
