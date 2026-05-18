# AGENTS

This file is the main entry point for `ofpm` project rules.

Before changing code or docs, read these documents in order:

1. [`.ai/project-direction.md`](.ai/project-direction.md)
   - product direction, command model, builder vs target split
2. [`.ai/architecture.md`](.ai/architecture.md)
   - truth sources, repo model, package recipe model, managed-root model
3. [`.ai/terms.md`](.ai/terms.md)
   - preferred vocabulary for repo, package, payload, state, dependency, integration
4. [`.ai/code-organization.md`](.ai/code-organization.md)
   - where new code and docs should live
5. [`.ai/protocols/README.md`](.ai/protocols/README.md)
   - task-specific working rules and implementation discipline
6. [`.ai/verification.md`](.ai/verification.md)
   - validation expectations and test selection policy
7. [`.ai/workflow.md`](.ai/workflow.md)
   - session hygiene, temporary files, durable notes
8. [`.ai/decision-log.md`](.ai/decision-log.md)
   - already agreed decisions that should stay stable unless deliberately changed

Core expectations:

- Use `ofpm` consistently for project, CLI, Python package, and managed-root naming.
- Keep target-side commands offline-only.
- Treat a copied repo snapshot as the main offline transfer unit.
- Keep package definitions self-owned under repo package directories.
- Prefer package-manager-like UX, especially `yum`/`dnf`-style verbs.
- Keep `depends` for required relationships only.
- Keep optional relationships under `integrations`, not fake optional dependencies.
