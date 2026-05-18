# ofpm Architecture

## Core Idea

`ofpm` is a personal offline package manager.

Its interface should feel familiar to users of `apt`, `yum`, or `dnf`, while using a portable repo
snapshot as the main transfer unit.

The intended flow is:

- builder-side local sources or provider downloads
- import into an `ofpm` repo
- copy the repo to the target machine
- register the repo and run offline package-manager commands

## Truth Sources

Before placing code or changing a workflow, ask:

```text
What is the authoritative truth source for this behavior or data?
```

Then ask:

```text
Is this repo definition truth, provider snapshot truth, installed-state truth, or CLI presentation?
```

Do not place code by convenience or by the first caller. Place it by ownership.

### Repo Definition Truth

Repo definition truth lives in package-local `package.py` definitions.

Locations:

- `repos/<name>/ofpm/<package>/<version>/package.py`
- `repos/<name>/apt/<package>/<version>/package.py`

Owns:

- package identity
- version
- target compatibility metadata
- required dependencies
- optional integrations
- env metadata
- install/remove/verify behavior when generic behavior is insufficient

### Provider Snapshot Truth

Provider snapshot truth describes what was downloaded from an upstream package source.

Locations:

- `repos/<name>/apt/<package>/<version>/payload/`
- `ofpm/apt.py`

Owns:

- downloaded `.deb` artifacts
- provider metadata used to reconstruct or inspect the snapshot

### Installed-State Truth

Installed-state truth lives under the managed root.

Locations:

- `$HOME/.ofpm/state/`
- `/opt/ofpm/state/`

Owns:

- installed package records
- receipts
- ownership records
- install/remove history

### CLI Presentation Truth

CLI presentation code reports what repo and state truth say. It does not invent package meaning.

Locations:

- `ofpm/cli.py`

Owns:

- argument parsing
- output formatting
- command orchestration

Does not own:

- package-specific install rules
- package metadata
- provider acquisition semantics

## Builder vs Target Split

Builder-side commands:

- `ofpm source add <name> <path>`
- `ofpm source show <name>`
- `ofpm repo import <repo> --source <name> --package <package>`
- `ofpm apt list`
- `ofpm apt show <package>`
- `ofpm apt download <package>`
- `ofpm apt import <repo> <package>`

Target-side commands:

- `ofpm list`
- `ofpm show <package>`
- `ofpm install <package>`
- `ofpm upgrade <package>`
- `ofpm remove <package>`
- `ofpm verify <package>`
- `ofpm state`

Target-side commands must behave as offline-only operations.

## Repo Model

Users should not need to hand-edit repo internals in normal flows.

Current package layout:

- `repos/<name>/ofpm/<package>/<version>/package.py`
- `repos/<name>/ofpm/<package>/<version>/payload/`
- `repos/<name>/apt/<package>/<version>/package.py`
- `repos/<name>/apt/<package>/<version>/payload/`

The copied repo directory is the offline delivery unit.

## Package Model

Package-local `package.py` is the package-owned definition and behavior boundary.

Each package definition should keep:

- package identity and version
- target metadata
- required dependencies
- optional integrations
- env metadata
- payload file declarations

Generic actions should be metadata-driven.
Package-local methods should only add behavior that cannot be expressed cleanly through shared
install/remove/verify handling.

## Managed Roots

Managed roots:

- system root: `/opt/ofpm`
- user root: `$HOME/.ofpm`

Real package payloads should live under managed roots, not mixed into arbitrary system locations.

Automatic PATH integration is not required in phase 1.
PATH exposure should be user-controlled via shell config, wrapper policy, or `ofpm env`.
