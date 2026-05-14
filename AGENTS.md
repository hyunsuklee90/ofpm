# AGENTS

## Project Name

- Working name: `ofpm`
- Meaning: personal offline package manager
- Use `ofpm` for future CLI, Python package, and install root naming.
- Existing transitional naming should be normalized to `ofpm` in code and docs.

## Product Direction

- The target direction is a personal offline package manager, similar in spirit to a private offline `apt`/`yum`.
- Split the system conceptually into:
  - target-side offline package management
  - builder-side online artifact acquisition
- Treat the main offline transfer unit as a portable repo snapshot, not a bundle archive.
- The system must carry:
  - package metadata
  - available repo metadata
  - target state metadata
  - verification rules

## CLI and UX Policy

- Even though this is a personal tool, CLI behavior should stay close to established package manager conventions where practical.
- Prefer command shapes, terminology, and operator mental models that resemble `apt`, `yum`, or `dnf`.
- Before introducing or renaming a command, first present the closest `apt`/`yum`/`dnf` equivalents and explain the tradeoff.
- Let the user choose among a small set of familiar command patterns when multiple reasonable options exist.
- Default CLI reference model: mostly `yum`/`dnf` style, with selective borrowing from `apt` where it improves readability.
- Favor familiar actions such as:
  - `list`
  - `show`
  - `install`
  - `upgrade`
  - `remove`
  - `verify`
  - `state`
- When `ofpm` behavior differs from traditional package managers because of offline constraints, make that difference explicit in output and docs.
- Command output should explain:
  - what `ofpm` is checking
  - what it decided
  - which files or metadata drove that decision
- Keep output readable first, but detailed enough that the user can inspect referenced files when something looks wrong.

## Preferred Command Set

- Preferred phase-1 command family:
  - `ofpm source add <name> <path>`
  - `ofpm source show <name>`
  - `ofpm repo import <repo> --source <name> --package <package>`
  - `ofpm apt download <package>`
  - `ofpm apt import <repo> <package>`
  - `ofpm list`
  - `ofpm show <package>`
  - `ofpm install <package>`
  - `ofpm upgrade <package>`
  - `ofpm remove <package>`
  - `ofpm verify <package>`
  - `ofpm state`
- Treat these as the primary UX targets when evolving existing scaffold commands.
- For package detail inspection, prefer `show` over `info`.

## Scope Priorities

1. metadata structure
2. source and repo import structure
3. target state structure
4. artifact and blob store structure
5. full repo copy/import flow
6. target profiles and install layouts
7. dependency checks and later package-manager style install/upgrade flows

## Current Design Decisions

- Implementation language for phase 1: `Python`
- Assume `python3` is available on Linux/WSL targets.
- Supporting targets without Python is deferred.
- Default target policy: `OFPM_OFFLINE_STRICT=1`
- Target-side commands should not require or attempt network access.
- Real package payloads should live under managed roots, not mixed into arbitrary system locations.
- Managed roots:
  - system root: `/opt/ofpm`
  - user root: `$HOME/.ofpm`
- Automatic PATH integration is not required in phase 1.
- Internal execution under the managed root is enough for now.
- PATH exposure should be user-controlled via shell config, wrapper policy, or `ofpm env`.

## Package Model

- Separate logical package content from installation location policy.
- Example logical packages:
  - `ollama-runtime`
  - `ollama-model-*`
  - `node-runtime`
  - `pi-app`
  - `personal-config`
- Large model blobs should prefer whole-blob addition over binary diff patching.
- `ollama` runtime and model assets should remain separate packages.

## Layout Policy

- Support both system-root and user-root installs.
- Keep layouts tightly controlled rather than allowing arbitrary install paths.
- State must record the effective install root kind and path.
- Patch applicability should assume same layout/root family unless a future migration feature exists.
- Automatic layout migration is out of scope for phase 1.

## Dependency Policy

- Start with dependency checking, not a full solver.
- Phase 1 dependency scope:
  - package version requirements
  - profile requirements
  - layout/root requirements
  - conflicts
- Avoid file-level dependency modeling in phase 1.
- If dependency or state checks fail, prefer a conservative full reinstall path over forcing a partial update.

## Verification Policy

- `list`-only checks are insufficient.
- For `ollama`-style assets, verification should eventually include:
  - manifest closure validation
  - referenced blob existence and hash verification
  - `show`-level validation
  - actual `run` validation where feasible
- Distinguish restore correctness from runtime-resource failure.
- Example: successful restore but insufficient memory is a runtime constraint, not a restore corruption.

## Repository Policy

- Keep package-manager-owned content under the project-managed roots.
- Separate deployable payloads from validation/test harness assets.
- Docker offline test assets should be treated as verification scenarios, not ordinary deployed payloads.
- Users should not need to hand-edit repo internal directories in normal flows.
- The CLI should manage repo layout details such as `catalog/` and `artifacts/`.

## Network Policy

- Distinguish target-side commands from builder-side fetch commands.
- Target-side commands such as `install`, `upgrade`, `remove`, and `verify` should behave as offline-only operations.
- Builder-side acquisition commands such as `apt download` are allowed to be online by design, but their outputs must later be usable without network access.
- Offline transfer should prefer copying a prepared `repos/<name>` directory over bundle-specific workflows.
- When `ofpm` behavior differs because of offline constraints, surface that explicitly in command output.

## State Policy

- Use tool-owned JSON state for phase 1 rather than hand-edited YAML.
- Keep managed-root state split into:
  - installed package state
  - install receipts
  - ownership entries
  - install/remove history
- `ofpm remove` must be driven by recorded receipts, not by best-effort path guessing.
- For external providers such as `apt`, record enough ownership information to avoid removing shared dependencies that are still referenced by another install.
- If removal safety is ambiguous, prefer conservative behavior over aggressive deletion.

## Catalog Policy

- Keep package definitions and actual artifact presence as separate concerns.
- Package definitions may exist even when source artifacts are currently unavailable.
- Default `ofpm list` behavior should show only currently available packages.
- `ofpm list --all` should expose unavailable package definitions too.
- `ofpm show <package>` should clearly report missing artifact sources when they exist.
- Favor configurable artifact source roots over permanently hardcoded machine-specific paths as the design evolves.

## Next Implementation Intent

- Keep scaffold concepts aligned with `ofpm`.
- Keep `source` for local builder-side paths and `apt` for provider-side acquisition.
- Keep `repo import` as the main way to turn builder-side inputs into portable repo packages.
- Add explicit layout metadata for system root vs user root.
- Add catalog/index concepts for installable package discovery.
- Add dependency fields to package metadata.
- Import selected assets from `/mnt/d/OneDrive/0project/harness/pi` incrementally.
