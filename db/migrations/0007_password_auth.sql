-- R2M 0007: password sign-in. scrypt hashes ("scrypt$<salt>$<key>", base64url); a user without a hash cannot sign
-- in and any session issued before this migration stops resolving. Set hashes with scripts/set_password.py.
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash text;

INSERT INTO schema_migrations(version) VALUES ('0007_password_auth') ON CONFLICT DO NOTHING;
COMMIT;
