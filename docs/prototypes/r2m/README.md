# R2M frontend design reference

Browser-only HTML/CSS/JavaScript prototype with white surfaces, graphite text, neon-lime accents, and reduced-motion support. All metrics, approvals, and execution outcomes are synthetic browser fixtures. No credentials, external services, or backend are used.

Open `dist/index.html` directly, or run from the repository root:

```sh
node docs/prototypes/r2m/serve.cjs
```

Visit http://127.0.0.1:4173. Stop another preview using that port first.

## Relationship to the implementation spec

This is the earlier visual exploration, not the production `web/` implementation. Follow `dev_docs/DEVELOPER_SPEC.md` for the actual application architecture. In particular:

- Replace the support/refund workload with OpsPilot and synthetic payments-api operations.
- Introduce Atlas Applied AI and Meridian Financial perspectives and demo roles.
- Use code-owned policies, revision hashes, and customer approvals.
- Keep evaluations in the pre-deployment build gate; runtime policy checks are separate.
- Build the Next.js frontend against the FastAPI contracts; don't reuse browser fixtures as live metrics.
- Keewano is optional; Sparta is excluded by the current spec.

Reuse the visual language and interaction concepts while adapting information architecture to that contract. This reference is intentionally separate from the prescribed application package layout.
