# ofpm Workflow

## Working Style

- Keep changes aligned with `ofpm` package-manager terminology and direction.
- Prefer small, ownership-respecting edits over convenience-layer sprawl.
- When changing structure, update the durable `.ai` notes if the rule is expected to persist.

## Session Hygiene

- Do not create throwaway files in the repo root.
- Keep temporary experiment files out of durable project docs.
- If a temporary script or output is needed, prefer a clearly temporary location such as `temp/`
  or a scenario-specific test workspace.

## Durable Notes

Use `.ai/*.md` for rules that should survive beyond the current session.

Typical durable note categories:

- architecture or truth-source rules
- terminology decisions
- verification expectations
- workflow and organization conventions

Use `.ai/decision-log.md` for decisions that were deliberately made and may need historical context.

## Refactor Discipline

Before adding a new helper or module, ask:

```text
Does this helper own a real reusable concept, or am I hiding a placement mistake?
```

Prefer:

- metadata-first generic behavior
- package-local overrides only for true special cases
- one clear ownership boundary per behavior

Avoid:

- optional behavior encoded as fake required metadata
- duplicated helper layers that only forward arguments
- putting package-specific semantics into generic runtime files
