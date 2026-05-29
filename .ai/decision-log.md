# ofpm Decision Log

## 2026-05-12

### Naming

- Chosen CLI and project name: `ofpm`
- `opm` was rejected because it already collides with multiple existing tools, including OpenResty `opm` and OKD/OpenShift `opm`

### Implementation

- Phase 1 language: `Python`
- Assume `python3` exists on Linux/WSL targets
- Self-contained no-Python bootstrap is deferred

### Installation Model

- Support both system-root and user-root installation
- system-root base: `/opt/ofpm`
- user-root base: `$HOME/.ofpm`
- Keep managed package content inside those roots
- Do not require PATH integration in phase 1

### Package Manager Direction

- Project direction changed from generic bundle tool toward personal offline package manager
- Future target-side usage should feel closer to a private offline `apt`/`yum`
- The system should eventually carry its own package catalog plus installed state
- CLI and command naming should track familiar package-manager conventions where practical
- Output should explain decisions clearly enough that the user can learn from the flow, not just see success/failure
- Chosen command-model bias: primarily `yum`/`dnf`, with selective `apt` borrowing
- Preferred command set:
  - `list`
  - `show`
  - `install`
  - `upgrade`
  - `remove`
  - `verify`
  - `state`

### Network Direction

- Target-side package management should default to offline-strict behavior
- Builder-side artifact acquisition should be represented as separate provider wrapper commands
- Builder-side provider helper focus moved to local repo construction such as `apt build-repo`
- Preferred offline transfer workflow: prepare a portable repo snapshot and copy the repo directory
- Local builder-side directories should be passed directly to `repo import --path`
- Release archives may be passed directly to `repo import-archive --archive`

### State Direction

- Phase 1 keeps tool-owned managed-root state in JSON
- Do not use hand-edited YAML for install/remove tracking
- Split managed-root state into:
  - `installed`
  - `receipts`
  - `ownership`
  - `history`
- `remove` behavior should be receipt-driven
- Shared dependency handling for external providers such as `apt` should later build on `ownership` entries rather than ad hoc package deletion

### Dependency Model

- Start with applicability checks, not a full dependency solver
- Phase 1 checks should include:
  - package/version requirements
  - profile requirements
  - install root/layout requirements
  - conflicts

### Layout Model

- Installation location must affect patch applicability and verification
- Layout migration is not a phase 1 feature
- If layout/root family differs, prefer full reinstall over migration

### Verification Model

- `ollama list` alone is not enough
- verification should progress toward:
  - closure validation
  - blob integrity checks
  - `show` validation
  - real run validation
- restore integrity and runtime resource sufficiency must remain separate statuses

### External Asset Integration

- Existing assets under `/mnt/d/OneDrive/0project/harness/pi` should be imported incrementally
- Treat Docker offline test materials as verification assets rather than normal deployment payloads
