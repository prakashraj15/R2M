-- R2M 0004: SDK registration and event ingestion in one database round trip each.
--
-- The hosted database can be hundreds of milliseconds away. The per-event / per-component statements in the
-- application exceeded the SDK's 5 s timeout (registration ~10 s, a 30-event ingest batch > 30 s). The same
-- logic now runs inside Postgres; Python still owns sanitizing, evidence hashing, incidents and the outbox.
BEGIN;

-- Ingestion: SECURITY INVOKER, so the caller's row-level-security scope (the SDK credential's pair) still applies.
-- Each event runs in its own subtransaction: a bad event is rejected without losing the rest of the batch.
-- Events arrive pre-shaped by the app: sanitized `attributes`, plus `_event_attrs`, `_component`, `_usage`.
CREATE OR REPLACE FUNCTION public.r2m_ingest_batch(p_vendor uuid, p_customer uuid, p_events jsonb)
RETURNS TABLE(event_id uuid, outcome text, installation_id uuid) LANGUAGE plpgsql AS $$
#variable_conflict use_column
DECLARE
  e jsonb; v_event uuid; v_dep uuid; v_exec uuid; v_trace uuid; v_span uuid; v_parent uuid; v_at timestamptz;
  v_kind text; v_attrs jsonb; v_inst uuid; v_agent uuid; v_cust uuid; v_vendor uuid; v_new uuid; v_ok boolean;
  v_row record; s uuid;
BEGIN
  FOR e IN SELECT x.value FROM jsonb_array_elements(p_events) x ORDER BY (x.value->>'occurred_at')::timestamptz LOOP
    v_event := (e->>'event_id')::uuid;
    v_dep := (e->>'deployment_id')::uuid;
    v_at := (e->>'occurred_at')::timestamptz;
    v_kind := e->>'kind';
    v_attrs := coalesce(e->'attributes', '{}'::jsonb);
    v_exec := (e->>'execution_id')::uuid;
    v_span := (e->>'span_id')::uuid;
    v_parent := (e->>'parent_span_id')::uuid;
    v_trace := coalesce((e->>'trace_id')::uuid, v_exec);  -- SDK default: trace_id = execution_id
    event_id := v_event; installation_id := NULL;

    SELECT d.installation_id, i.agent_id, i.customer_org_id, a.vendor_org_id INTO v_inst, v_agent, v_cust, v_vendor
      FROM public.deployments d JOIN public.agent_installations i ON i.id = d.installation_id
      JOIN public.agents a ON a.id = i.agent_id WHERE d.id = v_dep;
    IF NOT FOUND OR (e->>'vendor_org_id')::uuid IS DISTINCT FROM p_vendor
       OR (e->>'customer_org_id')::uuid IS DISTINCT FROM p_customer OR v_agent IS DISTINCT FROM (e->>'agent_id')::uuid
       OR v_cust <> p_customer OR v_vendor <> p_vendor THEN
      outcome := 'scope_mismatch'; RETURN NEXT; CONTINUE;
    END IF;
    installation_id := v_inst;

    IF v_exec IS NULL THEN
      IF v_kind <> 'heartbeat' THEN outcome := 'execution_required'; RETURN NEXT; CONTINUE; END IF;
      UPDATE public.agent_installations SET last_heartbeat_at = greatest(coalesce(last_heartbeat_at, v_at), v_at) WHERE id = v_inst;
      outcome := 'accepted'; RETURN NEXT; CONTINUE;
    END IF;

    BEGIN
      INSERT INTO public.executions(id, deployment_id, customer_org_id, trace_id, status, started_at)
        VALUES (v_exec, v_dep, p_customer, v_trace, 'running', v_at) ON CONFLICT (id) DO NOTHING;
      SELECT x.deployment_id, x.trace_id INTO v_row FROM public.executions x WHERE x.id = v_exec;
      IF v_row.deployment_id <> v_dep OR v_row.trace_id <> v_trace THEN
        RAISE EXCEPTION 'execution mismatch' USING ERRCODE = 'R2M01';
      END IF;
      -- Out-of-order tolerant: parent/span may not exist yet; create placeholders completed by later events.
      FOREACH s IN ARRAY array_remove(ARRAY[v_parent, v_span], NULL) LOOP
        INSERT INTO public.spans(id, execution_id, kind, name, status, started_at)
          VALUES (s, v_exec, 'unknown', '(pending)', 'placeholder', v_at) ON CONFLICT (id) DO NOTHING;
        SELECT sp.execution_id = v_exec INTO v_ok FROM public.spans sp WHERE sp.id = s;
        IF NOT v_ok THEN RAISE EXCEPTION 'span mismatch' USING ERRCODE = 'R2M02'; END IF;
      END LOOP;

      v_new := NULL;
      INSERT INTO public.execution_events(id, execution_id, span_id, event_type, occurred_at, severity, status, attributes)
        VALUES (v_event, v_exec, v_span, v_kind, v_at, coalesce(e->>'severity', 'info'), e->>'status', coalesce(e->'_event_attrs', v_attrs))
        ON CONFLICT (id) DO NOTHING RETURNING id INTO v_new;
      IF v_new IS NULL THEN
        outcome := 'duplicate';
      ELSE
        IF v_kind = 'execution.started' THEN
          UPDATE public.executions SET started_at = least(started_at, v_at), scenario = coalesce(v_attrs->>'scenario', scenario),
                 metadata = metadata || v_attrs, status = 'running', ended_at = NULL WHERE id = v_exec;
        ELSIF v_kind = 'execution.ended' THEN
          UPDATE public.executions SET ended_at = v_at,
                 status = CASE WHEN e->>'status' IN ('completed', 'failed', 'cancelled') THEN e->>'status' ELSE 'completed' END
           WHERE id = v_exec;
        ELSIF v_kind = 'span' AND v_span IS NOT NULL THEN
          -- SDK emits each span once, when it ends: occurred_at = start, duration_ms = length.
          UPDATE public.spans SET parent_span_id = v_parent, kind = coalesce(e->>'span_kind', 'span'), name = e->>'name',
                 status = coalesce(e->>'status', 'ok'), started_at = v_at, duration_ms = (e->>'duration_ms')::numeric,
                 ended_at = v_at + make_interval(secs => coalesce((e->>'duration_ms')::float8, 0) / 1000.0),
                 attributes = attributes || v_attrs
           WHERE id = v_span;
        ELSIF v_kind = 'usage' AND e ? '_usage' THEN
          INSERT INTO public.usage_records(execution_id, span_id, component_kind, input_tokens, output_tokens, amount_usd,
                                           cost_source, duration_ms, occurred_at)
          VALUES (v_exec, v_span, e->'_usage'->>'component_kind', (e->'_usage'->>'input_tokens')::bigint,
                  (e->'_usage'->>'output_tokens')::bigint, (e->'_usage'->>'amount_usd')::numeric,
                  e->'_usage'->>'cost_source', (e->'_usage'->>'duration_ms')::numeric, v_at);
        END IF;
        UPDATE public.agent_installations SET last_heartbeat_at = greatest(coalesce(last_heartbeat_at, v_at), v_at) WHERE id = v_inst;
        IF e->>'_component' IS NOT NULL THEN
          UPDATE public.agent_components SET last_seen_at = greatest(coalesce(last_seen_at, v_at), v_at)
           WHERE agent_components.installation_id = v_inst AND component_key = e->>'_component';
        END IF;
        outcome := 'accepted';
      END IF;
    EXCEPTION
      WHEN unique_violation OR SQLSTATE 'R2M01' THEN outcome := 'execution_mismatch';  -- trace_id reused elsewhere
      WHEN SQLSTATE 'R2M02' THEN outcome := 'span_mismatch';
    END;
    RETURN NEXT;
  END LOOP;
END $$;

-- SDK agent registration. SECURITY DEFINER: it may create an installation the caller cannot see yet (the app has
-- already checked the SDK credential's vendor/customer pair; this re-checks the link). Returns no row when the
-- pair is not actively linked. New builds only ever get a 'proposed' deployment.
CREATE OR REPLACE FUNCTION public.r2m_register_sdk_agent(
  p_vendor uuid, p_customer uuid, p_environment text, p_slug text, p_name text, p_description text,
  p_sdk_version text, p_build_version text, p_source_digest text, p_artifact_digest text,
  p_components jsonb, p_edges jsonb)
RETURNS TABLE(agent_id uuid, installation_id uuid, deployment_id uuid, deployment_status text)
LANGUAGE plpgsql SECURITY DEFINER AS $$
#variable_conflict use_column
DECLARE v_agent uuid; v_inst uuid; v_build uuid; v_version text; v_dep uuid; v_status text; v_missing int;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.vendor_customer_links l JOIN public.organizations v ON v.id = l.vendor_org_id
                 JOIN public.organizations c ON c.id = l.customer_org_id
                 WHERE l.vendor_org_id = p_vendor AND l.customer_org_id = p_customer AND l.status = 'active'
                   AND v.kind = 'vendor' AND c.kind = 'customer') THEN
    RETURN;
  END IF;
  INSERT INTO public.agents(vendor_org_id, slug, name, description, sdk_version) VALUES (p_vendor, p_slug, p_name, p_description, p_sdk_version)
    ON CONFLICT (vendor_org_id, slug) DO UPDATE SET name = EXCLUDED.name,
       description = coalesce(EXCLUDED.description, agents.description), sdk_version = EXCLUDED.sdk_version
    RETURNING id INTO v_agent;
  INSERT INTO public.agent_installations(agent_id, customer_org_id, environment, status) VALUES (v_agent, p_customer, p_environment, 'active')
    ON CONFLICT (agent_id, customer_org_id, environment) DO UPDATE SET status = agent_installations.status
    RETURNING id INTO v_inst;
  INSERT INTO public.builds(agent_id, version, source_digest, artifact_digest) VALUES (v_agent, p_build_version, p_source_digest, p_artifact_digest)
    ON CONFLICT (agent_id, artifact_digest) DO UPDATE SET version = builds.version
    RETURNING id, version INTO v_build, v_version;
  IF v_version <> p_build_version THEN
    RAISE EXCEPTION 'artifact digest already registered under another version' USING ERRCODE = 'R2M10';
  END IF;
  SELECT d.id, d.status INTO v_dep, v_status FROM public.deployments d WHERE d.installation_id = v_inst AND d.build_id = v_build
   ORDER BY (d.status = 'deployed') DESC, d.created_at DESC LIMIT 1;
  IF v_dep IS NULL THEN
    INSERT INTO public.deployments(installation_id, build_id, status) VALUES (v_inst, v_build, 'proposed') RETURNING id, status INTO v_dep, v_status;
  END IF;

  INSERT INTO public.agent_components(installation_id, component_key, kind, label, metadata)
  SELECT v_inst, c->>'component_key', c->>'kind', c->>'label', coalesce(c->'metadata', '{}'::jsonb)
    FROM jsonb_array_elements(coalesce(p_components, '[]'::jsonb)) c
  ON CONFLICT (installation_id, component_key) DO UPDATE SET kind = EXCLUDED.kind, label = EXCLUDED.label, metadata = EXCLUDED.metadata;

  SELECT count(*) INTO v_missing FROM jsonb_array_elements(coalesce(p_edges, '[]'::jsonb)) e
   WHERE e->>'source' = e->>'target'
      OR NOT EXISTS (SELECT 1 FROM public.agent_components c WHERE c.installation_id = v_inst AND c.component_key = e->>'source')
      OR NOT EXISTS (SELECT 1 FROM public.agent_components c WHERE c.installation_id = v_inst AND c.component_key = e->>'target');
  IF v_missing > 0 THEN
    RAISE EXCEPTION 'edges reference unknown components' USING ERRCODE = 'R2M11';
  END IF;
  INSERT INTO public.component_edges(installation_id, source_component_id, target_component_id, edge_kind)
  SELECT DISTINCT v_inst, s.id, t.id, coalesce(e->>'edge_kind', 'calls')
    FROM jsonb_array_elements(coalesce(p_edges, '[]'::jsonb)) e
    JOIN public.agent_components s ON s.installation_id = v_inst AND s.component_key = e->>'source'
    JOIN public.agent_components t ON t.installation_id = v_inst AND t.component_key = e->>'target'
   WHERE NOT EXISTS (SELECT 1 FROM public.component_edges x WHERE x.installation_id = v_inst AND x.source_component_id = s.id
                     AND x.target_component_id = t.id AND x.edge_kind = coalesce(e->>'edge_kind', 'calls'));

  INSERT INTO public.audit_events(actor_user_id, organization_id, action, target_type, target_id, details)
  VALUES (NULL, p_vendor, 'sdk.agent.register', 'deployment', v_dep,
          jsonb_build_object('slug', p_slug, 'build_version', p_build_version, 'artifact_digest', p_artifact_digest,
                             'environment', p_environment, 'deployment_status', v_status));
  RETURN QUERY SELECT v_agent, v_inst, v_dep, v_status;
END $$;

INSERT INTO schema_migrations(version) VALUES ('0004_one_round_trip_sdk') ON CONFLICT DO NOTHING;
COMMIT;
