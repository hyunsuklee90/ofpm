## Test Layout

- `fixtures/repos/minimal/`: git-tracked lightweight test repo used by automated tests
- `/tmp/ofpm-tests` by default: ignored working trees created during test runs
- `test_cli_scenarios.py`: CLI smoke and policy tests

The minimal repo is intentionally tiny. It is used to validate install/remove,
dependency checks, env rendering, and root-selection policy without depending on
large real payloads under `repos/ofpm/main` or local large-payload repos.
