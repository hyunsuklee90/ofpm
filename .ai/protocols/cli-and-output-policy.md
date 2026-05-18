# CLI And Output Policy

## Command Shape

- Keep command shapes close to familiar package-manager models where practical.
- Prefer `yum`/`dnf`-style verbs with selective `apt` borrowing only when it improves clarity.
- Prefer `show` over `info`.

## Output Rules

Command output should explain:

- what `ofpm` checked
- what `ofpm` decided
- which files, package definitions, or state records drove that decision

## Readability Rules

- readable first
- inspectable second
- no silent magic when a package-manager-style explanation is possible

## Offline Rules

When behavior differs from traditional package managers because of offline constraints, say so
explicitly in output or docs.

## Detail Rules

- `show` should surface package identity, target, install root, dependencies, integrations, and
  availability
- install/remove/verify output should make the managed root and package definition visible
