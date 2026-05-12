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
- Builder-side artifact acquisition should be represented as separate `fetch ...` commands
- First planned online acquisition command family: `fetch apt`
- Preferred offline transfer workflow: `export` selected packages into bundle dir or archive

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
