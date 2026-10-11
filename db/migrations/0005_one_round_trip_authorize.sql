-- R2M 0005: the runtime action gate (/actions/authorize) in one database round trip.
--
-- Same checks, same order, same reason codes as the previous application implementation (see 0004 for why).
-- SECURITY INVOKER: the SDK credential's row-level-security scope still applies to every lookup and write.
-- Python keeps what must stay outside the DB: nonce generation, HMAC grant signing and evidence hashing.
BEGIN;

CREATE OR REPLACE FUNCTION public.r2m_authorize(
  p_customer uuid,          -- SDK credential's customer (tenant scope)
  r jsonb,                  -- request; `arguments` already sanitized by the app
  p_nonce_hash text,        -- sha256 of the grant nonce, used only if the decision is ALLOW
  p_grant_expires timestamptz,
  p_approval_ttl_seconds int)
RETURNS jsonb LANGUAGE plpgsql AS $$
#variable_conflict use_column
DECLARE
  v_dep record; v_row record; v_act record; v_rev record; v_approval record; p jsonb;
  v_exec uuid := (r->>'execution_id')::uuid;
  v_trace uuid := (r->>'trace_id')::uuid;
  v_span uuid := (r->>'span_id')::uuid;
  v_tool text := r->>'tool';
  v_hash text := r->>'arguments_hash';
  v_action uuid; v_decision text; v_reasons text[]; v_local text; v_local_codes text[]; v_missing text[];
  v_cited uuid[] := '{}'; v_unapproved text[] := '{}'; v_decision_ids uuid[] := '{}'; v_did uuid;
  v_approval_id uuid; v_approval_status text; v_grant uuid;
  v_rank jsonb := '{"ALLOW": 0, "REQUIRE_APPROVAL": 1, "DENY": 2}';
BEGIN
  -- 1. Tenant scope: deployment, installation, agent, customer and environment must line up.
  SELECT d.id, d.status, d.installation_id, i.customer_org_id, i.agent_id, i.environment INTO v_dep
    FROM public.deployments d JOIN public.agent_installations i ON i.id = d.installation_id
   WHERE d.id = (r->>'deployment_id')::uuid;
  IF NOT FOUND OR (r->>'customer_org_id')::uuid IS DISTINCT FROM p_customer
     OR v_dep.installation_id IS DISTINCT FROM (r->>'installation_id')::uuid OR v_dep.agent_id IS DISTINCT FROM (r->>'agent_id')::uuid
     OR v_dep.customer_org_id <> p_customer OR v_dep.environment IS DISTINCT FROM r->>'environment' THEN
    RETURN jsonb_build_object('decision', 'DENY', 'reason_codes', jsonb_build_array('TENANT_SCOPE_INVALID'));
  END IF;

  -- Execution (and span placeholder) may not have been ingested yet.
  BEGIN
    INSERT INTO public.executions(id, deployment_id, customer_org_id, trace_id, status, started_at)
      VALUES (v_exec, v_dep.id, v_dep.customer_org_id, v_trace, 'running', now()) ON CONFLICT (id) DO NOTHING;
  EXCEPTION WHEN unique_violation THEN
    RAISE EXCEPTION 'execution is bound to a different deployment or trace' USING ERRCODE = 'R2M20';
  END;
  SELECT x.deployment_id, x.trace_id INTO v_row FROM public.executions x WHERE x.id = v_exec;
  IF v_row.deployment_id <> v_dep.id OR v_row.trace_id <> v_trace THEN
    RAISE EXCEPTION 'execution is bound to a different deployment or trace' USING ERRCODE = 'R2M20';
  END IF;
  IF v_span IS NOT NULL THEN
    INSERT INTO public.spans(id, execution_id, kind, name, status, started_at)
      VALUES (v_span, v_exec, 'unknown', '(pending)', 'placeholder', now()) ON CONFLICT (id) DO NOTHING;
  END IF;

  -- 2. A resumed action must match the stored one exactly.
  IF r->>'action_id' IS NOT NULL THEN
    SELECT t.id, t.tool_key, t.arguments_hash, t.execution_id INTO v_act
      FROM public.tool_actions t WHERE t.id = (r->>'action_id')::uuid FOR UPDATE;
    IF NOT FOUND OR v_act.tool_key <> v_tool OR v_act.arguments_hash <> v_hash OR v_act.execution_id <> v_exec THEN
      RETURN jsonb_build_object('decision', 'DENY', 'reason_codes', jsonb_build_array('ACTION_BINDING_MISMATCH'));
    END IF;
    v_action := v_act.id;
  ELSE
    INSERT INTO public.tool_actions(execution_id, span_id, tool_key, arguments_hash, arguments)
      VALUES (v_exec, v_span, v_tool, v_hash, coalesce(r->'arguments', '{}'::jsonb)) RETURNING id INTO v_action;
  END IF;

  -- 3-6. Evaluate. Fail closed first; the server never relaxes the strictest local verdict.
  IF v_dep.status <> 'deployed' THEN
    v_decision := 'DENY'; v_reasons := ARRAY['DEPLOYMENT_NOT_ACTIVE'];
  ELSE
    FOR p IN SELECT value FROM jsonb_array_elements(coalesce(r->'policies', '[]'::jsonb)) LOOP
      SELECT pr.id, pr.version, pr.artifact_hash INTO v_rev
        FROM public.policy_activations a JOIN public.policy_revisions pr ON pr.id = a.revision_id
       WHERE a.installation_id = v_dep.installation_id AND a.active AND (a.expires_at IS NULL OR a.expires_at > now())
         AND pr.policy_key = p->>'policy_id'
       ORDER BY a.activated_at DESC LIMIT 1;
      IF FOUND AND v_rev.artifact_hash = p->>'artifact_hash' AND v_rev.version = p->>'version' THEN
        v_cited := v_cited || v_rev.id;
      ELSE
        v_unapproved := v_unapproved || ('POLICY_NOT_APPROVED:' || (p->>'policy_id'));
      END IF;
    END LOOP;
    IF cardinality(v_unapproved) > 0 THEN
      v_decision := 'DENY'; v_reasons := v_unapproved;
    ELSE
      -- Every policy ever registered for this agent that governs the tool must be cited.
      SELECT array_agg(k ORDER BY k) INTO v_missing FROM (
        SELECT DISTINCT pr.policy_key AS k FROM public.policy_revisions pr
         WHERE pr.agent_id = v_dep.agent_id AND pr.definition_metadata->'tools' ? v_tool
           AND pr.policy_key NOT IN (SELECT c.policy_key FROM public.policy_revisions c WHERE c.id = ANY(v_cited))) m;
      IF v_missing IS NOT NULL THEN
        v_decision := 'DENY';
        SELECT array_agg('GOVERNING_POLICY_NOT_CITED:' || k ORDER BY k) INTO v_reasons FROM unnest(v_missing) k;
      ELSE
        SELECT d INTO v_local FROM (SELECT r->>'local_decision' AS d UNION ALL
                                    SELECT value->>'decision' FROM jsonb_array_elements(coalesce(r->'policies', '[]'::jsonb))) x
         ORDER BY (v_rank->>d)::int DESC NULLS LAST LIMIT 1;
        SELECT array_agg(value->>'reason_code') INTO v_local_codes FROM jsonb_array_elements(coalesce(r->'policies', '[]'::jsonb))
         WHERE value->>'decision' = v_local AND coalesce(value->>'reason_code', '') <> '';
        IF v_local = 'DENY' THEN
          v_decision := 'DENY'; v_reasons := coalesce(v_local_codes, ARRAY['LOCAL_POLICY_DENY']);
        ELSIF v_local = 'ALLOW' THEN
          v_decision := 'ALLOW'; v_reasons := ARRAY['ALLOWED'];
        ELSE
          SELECT ra.id, ra.status, ra.expires_at INTO v_approval FROM public.runtime_approvals ra
           WHERE ra.action_id = v_action ORDER BY ra.requested_at DESC LIMIT 1 FOR UPDATE;
          IF NOT FOUND THEN
            INSERT INTO public.runtime_approvals(action_id, status, expires_at)
              VALUES (v_action, 'pending', now() + make_interval(secs => p_approval_ttl_seconds))
              RETURNING id, status, expires_at INTO v_approval;
          END IF;
          v_approval_id := v_approval.id; v_approval_status := v_approval.status;
          IF v_approval_status IN ('pending', 'approved') AND v_approval.expires_at <= now() THEN
            UPDATE public.runtime_approvals SET status = 'expired' WHERE id = v_approval_id;
            v_approval_status := 'expired';
          END IF;
          IF v_approval_status = 'pending' THEN
            v_decision := 'REQUIRE_APPROVAL'; v_reasons := coalesce(v_local_codes, ARRAY['HUMAN_APPROVAL_REQUIRED']);
          ELSIF v_approval_status <> 'approved' THEN
            v_decision := 'DENY'; v_reasons := ARRAY['APPROVAL_' || upper(v_approval_status)];
          ELSE
            v_decision := 'ALLOW'; v_reasons := ARRAY['HUMAN_APPROVED'];
          END IF;
        END IF;
      END IF;
    END IF;
  END IF;

  -- Persist. Later decisions never rewrite an action that already executed.
  UPDATE public.tool_actions SET
         outcome = CASE v_decision WHEN 'ALLOW' THEN 'authorized' WHEN 'DENY' THEN 'denied' ELSE 'pending_approval' END,
         authorized_at = CASE WHEN v_decision = 'ALLOW' THEN now() ELSE authorized_at END
   WHERE id = v_action AND executed_at IS NULL;
  FOR v_rev IN SELECT pr.id, pr.policy_key, pr.version, pr.artifact_hash FROM unnest(v_cited) WITH ORDINALITY c(id, n)
               JOIN public.policy_revisions pr ON pr.id = c.id ORDER BY c.n LOOP
    INSERT INTO public.policy_decisions(execution_id, action_id, revision_id, decision, reason_code, details)
    VALUES (v_exec, v_action, v_rev.id, lower(v_decision), left(array_to_string(v_reasons, ','), 500),
            jsonb_build_object('tool', v_tool, 'risk', r->>'risk', 'arguments_hash', v_hash, 'local_decision', r->>'local_decision',
                               'local_results', coalesce(r->'policies', '[]'::jsonb), 'approval_id', v_approval_id,
                               'policy', jsonb_build_object('key', v_rev.policy_key, 'version', v_rev.version, 'hash', v_rev.artifact_hash)))
    RETURNING id INTO v_did;
    v_decision_ids := v_decision_ids || v_did;
  END LOOP;
  IF cardinality(v_decision_ids) = 0 THEN
    INSERT INTO public.policy_decisions(execution_id, action_id, revision_id, decision, reason_code, details)
    VALUES (v_exec, v_action, NULL, lower(v_decision), left(array_to_string(v_reasons, ','), 500),
            jsonb_build_object('tool', v_tool, 'risk', r->>'risk', 'arguments_hash', v_hash, 'local_decision', r->>'local_decision',
                               'local_results', coalesce(r->'policies', '[]'::jsonb), 'approval_id', v_approval_id, 'policy', NULL))
    RETURNING id INTO v_did;
    v_decision_ids := v_decision_ids || v_did;
  END IF;

  IF v_decision = 'ALLOW' THEN
    IF v_approval_status = 'approved' THEN  -- one grant per approval
      UPDATE public.runtime_approvals SET status = 'consumed' WHERE id = v_approval_id;
    END IF;
    INSERT INTO public.action_grants(action_id, customer_org_id, deployment_id, execution_id, policy_revision_ids,
                                     tool_key, arguments_hash, nonce_hash, expires_at)
    VALUES (v_action, v_dep.customer_org_id, v_dep.id, v_exec, v_cited, v_tool, v_hash, p_nonce_hash, p_grant_expires)
    RETURNING id INTO v_grant;
  END IF;

  RETURN jsonb_build_object(
    'decision', v_decision, 'reason_codes', to_jsonb(v_reasons), 'decision_ids', to_jsonb(v_decision_ids),
    'action_id', v_action, 'policy_revision_ids', to_jsonb(v_cited), 'approval_id', v_approval_id,
    'approval_status', v_approval_status, 'grant_id', v_grant, 'installation_id', v_dep.installation_id,
    'customer_org_id', v_dep.customer_org_id, 'deployment_id', v_dep.id);
END $$;

INSERT INTO schema_migrations(version) VALUES ('0005_one_round_trip_authorize') ON CONFLICT DO NOTHING;
COMMIT;
