# ofpm Code Organization

This file defines where new `ofpm` code and docs should live.

## First Question

Before choosing a file, ask:

```text
What is the authoritative truth source for this behavior or data?
```

Then ask:

```text
Is this CLI orchestration, repo data access, runtime support, provider logic, or package-local behavior?
```

Do not place code by convenience or by the first caller.

## Primary Areas

### CLI

Locations:

- `ofpm/cli.py`

Use for:

- argument parsing
- command wiring
- readable output
- high-level command orchestration

Do not use for:

- package-specific install logic
- repo layout ownership
- provider-specific acquisition internals

### Repo Data

Locations:

- `ofpm/repo_data.py`
- `ofpm/package_def.py`

Use for:

- loading package definitions
- repo queries
- source resolution
- installed-state lookup helpers

Do not use for:

- user-facing formatting
- package-specific install/remove/verify behavior

### Runtime Support

Locations:

- `ofpm/runtime_support.py`
- `ofpm/installers.py`

Use for:

- generic file copy and removal helpers
- shared verification primitives
- receipt/state recording
- managed-root mechanics

Do not use for:

- package-specific semantic rules when they belong to a package recipe

### Provider Logic

Locations:

- `ofpm/apt.py`

Use for:

- external provider acquisition and snapshot shaping

Do not use for:

- generic repo queries already owned elsewhere
- package-local install semantics

### Package-Local Behavior

Locations:

- `repos/<name>/ofpm/<package>/<version>/package.py`
- `repos/<name>/apt/<package>/<version>/package.py`

Use for:

- package metadata
- required dependencies
- optional integrations
- package-specific install/remove/verify overrides

Rule:

- generic metadata-first behavior should stay in shared runtime support
- package-local methods should exist only when the package has behavior beyond generic handling

## Documentation Areas

### Project Entry

- `README.md`
- `AGENTS.md`

### Durable AI/Design Rules

- `.ai/*.md`

### Repo-Specific Notes

- `repos/main/README.md`
- `tests/README.md`

Rule:

- keep top-level `README.md` user-facing
- keep `.ai/*.md` for stable design and workflow rules
- keep repo-local READMEs narrow and concrete

## Lookup Guide

If you want to know where to look first, use this map.

### "How is a package defined?"

Look at:

- `repos/<name>/ofpm/<package>/<version>/package.py`
- `repos/<name>/apt/<package>/<version>/package.py`

### "How does a command behave?"

Look at:

- `ofpm/cli.py`

### "How are package definitions loaded?"

Look at:

- `ofpm/package_def.py`

### "How are repo contents discovered or queried?"

Look at:

- `ofpm/repo_data.py`

### "How does generic install/remove/verify work?"

Look at:

- `ofpm/installers.py`
- `ofpm/runtime_support.py`
- `ofpm/recipes.py`

### "How does apt provider acquisition work?"

Look at:

- `ofpm/apt.py`

### "Where is installed-state persistence handled?"

Look at:

- `ofpm/state_db.py`
- `ofpm/core.py`

### "Where are scenario tests?"

Look at:

- `tests/test_cli_scenarios.py`
- `tests/fixtures/repos/minimal/`
- `tests/README.md`
