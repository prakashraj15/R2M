-- R2M 0003: per-customer SDK credentials and Postgres row-level security.
--
-- The API connects as the migration (owner) login, then switches to r2m_app, a non-owner role without
-- BYPASSRLS, so the policies below apply to every query it runs. Per request the app sets three session
-- settings via the definer functions below: r2m.installations / r2m.orgs (what the caller may see) and
-- r2m.bypass (platform-internal work such as the outbox worker). Scripts run as the owner and are unaffected.
--
-- Threat model: RLS stops tenant leaks from an application query that forgets its scope filter. It is not a
-- defence against SQL injection (the session can change its own settings); all SQL is parameterized.
BEGIN;

CREATE TABLE IF NOT EXISTS sdk_credentials (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 vendor_org_id uuid NOT NULL,
 customer_org_id uuid NOT NULL,
 label text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 revoked_at timestamptz,
 FOREIGN KEY (vendor_org_id, customer_org_id) REFERENCES vendor_customer_links(vendor_org_id, customer_org_id));
CREATE UNIQUE INDEX IF NOT EXISTS uq_sdk_credential_label ON sdk_credentials(vendor_org_id, customer_org_id, label)
  WHERE revoked_at IS NULL;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'r2m_app') THEN
    CREATE ROLE r2m_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
GRANT r2m_app TO CURRENT_USER WITH SET TRUE, INHERIT FALSE;
GRANT USAGE ON SCHEMA public TO r2m_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO r2m_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO r2m_app;
-- Append-only and migration bookkeeping: the app role can never rewrite them.
REVOKE UPDATE, DELETE ON audit_events, evidence_items FROM r2m_app;
REVOKE INSERT, UPDATE, DELETE ON schema_migrations FROM r2m_app;

-- ---- scope settings ------------------------------------------------------
CREATE OR REPLACE FUNCTION public.r2m_bypass() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('r2m.bypass', true), '') = 'on' $$;
CREATE OR REPLACE FUNCTION public.r2m_installations() RETURNS uuid[] LANGUAGE sql STABLE AS
$$ SELECT coalesce(string_to_array(nullif(current_setting('r2m.installations', true), ''), ','), '{}')::uuid[] $$;
CREATE OR REPLACE FUNCTION public.r2m_orgs() RETURNS uuid[] LANGUAGE sql STABLE AS
$$ SELECT coalesce(string_to_array(nullif(current_setting('r2m.orgs', true), ''), ','), '{}')::uuid[] $$;

CREATE OR REPLACE FUNCTION public.r2m_set_scope(insts uuid[], orgs uuid[], bypass boolean) RETURNS void
LANGUAGE sql AS $$
  SELECT set_config('r2m.installations', array_to_string(coalesce(insts, '{}'), ','), false),
         set_config('r2m.orgs', array_to_string(coalesce(orgs, '{}'), ','), false),
         set_config('r2m.bypass', CASE WHEN bypass THEN 'on' ELSE 'off' END, false);
$$;

-- Browser actor: same rule as the application's SCOPE_SQL (own customer installs, or own vendor's agents at
-- actively linked customers). Sets the session scope and returns it so the app can reuse it.
CREATE OR REPLACE FUNCTION public.r2m_apply_actor_scope(uid uuid)
RETURNS TABLE(installations uuid[], orgs uuid[]) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE member_orgs uuid[]; insts uuid[]; visible uuid[];
BEGIN
  SELECT coalesce(array_agg(DISTINCT m.organization_id), '{}') INTO member_orgs FROM public.org_memberships m WHERE m.user_id = uid;
  SELECT coalesce(array_agg(i.id), '{}') INTO insts FROM public.agent_installations i JOIN public.agents a ON a.id = i.agent_id
   WHERE i.customer_org_id = ANY(member_orgs) OR (a.vendor_org_id = ANY(member_orgs) AND EXISTS (
         SELECT 1 FROM public.vendor_customer_links l WHERE l.vendor_org_id = a.vendor_org_id
         AND l.customer_org_id = i.customer_org_id AND l.status = 'active'));
  visible := member_orgs || coalesce((SELECT array_agg(DISTINCT i.customer_org_id) FROM public.agent_installations i
                                      WHERE i.id = ANY(insts)), '{}');
  PERFORM public.r2m_set_scope(insts, visible, false);
  RETURN QUERY SELECT insts, visible;
END $$;

-- SDK credential: only this vendor's agents at this customer. Empty result (and empty scope) if revoked/unlinked.
CREATE OR REPLACE FUNCTION public.r2m_apply_sdk_scope(cred uuid)
RETURNS TABLE(vendor_org_id uuid, customer_org_id uuid, installations uuid[], orgs uuid[])
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v uuid; c uuid; insts uuid[];
BEGIN
  SELECT s.vendor_org_id, s.customer_org_id INTO v, c FROM public.sdk_credentials s
    JOIN public.vendor_customer_links l ON l.vendor_org_id = s.vendor_org_id AND l.customer_org_id = s.customer_org_id
   WHERE s.id = cred AND s.revoked_at IS NULL AND l.status = 'active';
  IF v IS NULL THEN
    PERFORM public.r2m_set_scope('{}', '{}', false);
    RETURN;
  END IF;
  SELECT coalesce(array_agg(i.id), '{}') INTO insts FROM public.agent_installations i JOIN public.agents a ON a.id = i.agent_id
   WHERE a.vendor_org_id = v AND i.customer_org_id = c;
  PERFORM public.r2m_set_scope(insts, ARRAY[v, c], false);
  RETURN QUERY SELECT v, c, insts, ARRAY[v, c];
END $$;

-- ---- row predicates (definer: they look up parents without recursing through RLS) ----------------------
CREATE OR REPLACE FUNCTION public.r2m_inst_ok(inst uuid) RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT public.r2m_bypass() OR inst = ANY(public.r2m_installations()) $$;
CREATE OR REPLACE FUNCTION public.r2m_org_ok(org uuid) RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT public.r2m_bypass() OR org = ANY(public.r2m_orgs()) $$;
CREATE OR REPLACE FUNCTION public.r2m_dep_ok(dep uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER AS
$$ SELECT public.r2m_bypass() OR EXISTS (SELECT 1 FROM public.deployments d WHERE d.id = dep
          AND d.installation_id = ANY(public.r2m_installations())) $$;
CREATE OR REPLACE FUNCTION public.r2m_exec_ok(ex uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER AS
$$ SELECT public.r2m_bypass() OR EXISTS (SELECT 1 FROM public.executions e JOIN public.deployments d ON d.id = e.deployment_id
          WHERE e.id = ex AND d.installation_id = ANY(public.r2m_installations())) $$;
CREATE OR REPLACE FUNCTION public.r2m_action_ok(act uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER AS
$$ SELECT public.r2m_bypass() OR EXISTS (SELECT 1 FROM public.tool_actions t WHERE t.id = act AND public.r2m_exec_ok(t.execution_id)) $$;
CREATE OR REPLACE FUNCTION public.r2m_service_ok(svc uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER AS
$$ SELECT public.r2m_bypass() OR EXISTS (SELECT 1 FROM public.simulation_services s WHERE s.id = svc
          AND s.customer_org_id = ANY(public.r2m_orgs())) $$;
CREATE OR REPLACE FUNCTION public.r2m_integration_ok(integ uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER AS
$$ SELECT public.r2m_bypass() OR EXISTS (SELECT 1 FROM public.integration_configs c WHERE c.id = integ
          AND c.organization_id = ANY(public.r2m_orgs())) $$;

-- ---- policies -------------------------------------------------------------
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT * FROM (VALUES
      ('agent_installations', 'public.r2m_inst_ok(id)'),
      ('deployments', 'public.r2m_inst_ok(installation_id)'),
      ('agent_components', 'public.r2m_inst_ok(installation_id)'),
      ('component_edges', 'public.r2m_inst_ok(installation_id)'),
      ('policy_submissions', 'public.r2m_inst_ok(installation_id)'),
      ('policy_activations', 'public.r2m_inst_ok(installation_id)'),
      ('metric_points', 'public.r2m_inst_ok(installation_id)'),
      ('incidents', 'public.r2m_inst_ok(installation_id)'),
      ('evidence_items', 'public.r2m_inst_ok(installation_id)'),
      ('insight_queries', 'public.r2m_inst_ok(installation_id)'),
      ('executions', 'public.r2m_dep_ok(deployment_id)'),
      ('spans', 'public.r2m_exec_ok(execution_id)'),
      ('execution_events', 'public.r2m_exec_ok(execution_id)'),
      ('tool_actions', 'public.r2m_exec_ok(execution_id)'),
      ('policy_decisions', 'public.r2m_exec_ok(execution_id)'),
      ('usage_records', 'public.r2m_exec_ok(execution_id)'),
      ('action_grants', 'public.r2m_exec_ok(execution_id)'),
      ('runtime_approvals', 'public.r2m_action_ok(action_id)'),
      ('simulation_services', 'public.r2m_org_ok(customer_org_id)'),
      ('simulation_actions', 'public.r2m_service_ok(service_id)'),
      ('integration_configs', 'public.r2m_org_ok(organization_id)'),
      ('integration_outbox', 'public.r2m_integration_ok(integration_id)')) AS v(tbl, pred)
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tbl);
    EXECUTE format('DROP POLICY IF EXISTS r2m_tenant ON public.%I', t.tbl);
    EXECUTE format('CREATE POLICY r2m_tenant ON public.%I TO r2m_app USING (%s) WITH CHECK (%s)', t.tbl, t.pred, t.pred);
  END LOOP;
END $$;

-- Invariant triggers must see the whole picture regardless of the caller's scope.
ALTER FUNCTION public.r2m_check_submission() SECURITY DEFINER;
ALTER FUNCTION public.r2m_check_approval_decision() SECURITY DEFINER;
ALTER FUNCTION public.r2m_check_activation() SECURITY DEFINER;
ALTER FUNCTION public.r2m_check_deployment() SECURITY DEFINER;
ALTER FUNCTION public.r2m_check_edge() SECURITY DEFINER;
ALTER FUNCTION public.r2m_check_runtime_approval() SECURITY DEFINER;

INSERT INTO schema_migrations(version) VALUES ('0003_rls_and_sdk_credentials') ON CONFLICT DO NOTHING;
COMMIT;
