# Seed rules

`scripts/seed_demo.py` is idempotent: every row uses `ON CONFLICT DO NOTHING`, so re-running it never resets live demo state. To reset the synthetic service, use `POST /api/v1/operations/scenarios/{id}/reset`.

All IDs are deterministic UUIDv5:

```python
NS = uuid5(NAMESPACE_URL, "https://r2m.demo/seed")
uid(kind, key) = uuid5(NS, f"{kind}:{key}")
```

| kind | key examples |
|---|---|
| org | `atlas`, `meridian`, `northwind` |
| user | `dev@atlas.demo`, `security@meridian.demo`, … |
| agent | `opspilot` |
| installation | `opspilot:meridian`, `opspilot:northwind` |
| build | `1.0.0-seed` (placeholder digests, deployed so the demo agent works before the first real release) |
| deployment | `opspilot:meridian:1.0.0-seed` |
| component | `meridian:orchestrator`, `meridian:rollback_deployment`, … |
| service | `meridian:payments-api` |

Policies are **not** seeded. The SDK registers them at agent import with their real code hashes, and the demo then walks through submit → approve.

Everything is synthetic: fake organizations, `.demo` email addresses, and a simulated `payments-api`. Never seed real identities or tokens.
