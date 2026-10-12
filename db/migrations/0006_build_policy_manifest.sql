-- R2M 0006: per-build policy manifest. The SDK registers its policies together with the deployment (and so the
-- build) that ships them; the release gate requires exactly those revisions to be approved for the installation.
BEGIN;

CREATE TABLE IF NOT EXISTS build_policies (
 build_id uuid NOT NULL REFERENCES builds(id),
 policy_key text NOT NULL,
 revision_id uuid NOT NULL REFERENCES policy_revisions(id),
 registered_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (build_id, policy_key));
-- Builds and revisions are vendor-level (not tenant rows), like builds and policy_revisions themselves.
GRANT SELECT, INSERT, UPDATE ON build_policies TO r2m_app;

INSERT INTO schema_migrations(version) VALUES ('0006_build_policy_manifest') ON CONFLICT DO NOTHING;
COMMIT;
