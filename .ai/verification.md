# ofpm Verification Policy

## Minimum Expected Validation

Validation should match the feature area that changed.

- Run the most relevant existing tests for the touched command or package area.
- Prefer direct, as-built verification over theoretical coverage claims.
- If a required runtime mode or payload is unavailable, state that explicitly.

## Default Validation Levels

### Command-Level Validation

For CLI and repo logic changes, prefer:

- `python3 -m unittest tests.test_cli_scenarios`
- focused `python3 -m ofpm ...` command runs for the changed path

### Package-Level Validation

For package install/remove/verify changes, prefer:

- install
- verify
- remove

against the relevant managed-root test scenario.

### Repo-Layout Validation

For package definition or repo structure changes, prefer:

- `list`
- `show`
- source verification
- at least one install path through the changed structure

## Verification Rules

- `list`-only checks are not enough for install/remove changes.
- If code changes package-specific behavior, run the relevant scenario test and at least one direct
  CLI smoke path where feasible.
- If validation is skipped because the payload or environment is unavailable, say exactly what was
  unavailable.

## Long-Range Goal

For `ollama`-style assets, verification should keep progressing toward:

- manifest closure validation
- referenced blob existence and hash verification
- `show`-level validation
- actual `run` validation where feasible

Restore correctness and runtime-resource failure must remain separate statuses.
