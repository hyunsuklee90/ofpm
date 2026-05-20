# ofpm Project Direction

## Core Idea

`ofpm` is a personal offline package manager.

Its interface should feel familiar to users of `apt`, `yum`, or `dnf`, while using a portable repo snapshot as the main transfer unit.

The intended flow is:

- builder-side local paths or provider downloads
- import into an `ofpm` repo
- copy the repo to the target machine
- register the repo and run offline package-manager commands

## Design Principles

- repo snapshot first, bundle workflow later if ever needed
- content kept under repo-managed package directories using `package.py` and `payload/`
- target-aware management by install root kind and target metadata
- recorded target state for install, verify, and later upgrade decisions
- command and output conventions kept close to mainstream package manager UX

## Builder vs Target Split

Builder-side commands:

- `ofpm repo import <repo> --path <path> --package <package>`
- `ofpm apt list`
- `ofpm apt show <package>`
- `ofpm apt download <package>`

Target-side commands:

- `ofpm list`
- `ofpm show <package>`
- `ofpm install <package>`
- `ofpm upgrade <package>`
- `ofpm remove <package>`
- `ofpm verify <package>`
- `ofpm state`

## Managed State Direction

Managed installs should keep tool-owned JSON state under the managed root.

Phase-1 state split:

- `state/installed/`
- `state/receipts/`
- `state/ownership/`
- `state/history.json`

## Repo Model

Users should not need to hand-edit repo internals in normal flows.

The CLI should own repo structure details:

- local source registration under `local/`
- native packages under `repos/<name>/ofpm/<package>/<version>/`
- provider snapshots under `repos/<name>/<provider>/<package>/<version>/`
- payload content under each package-local `payload/`

The copied repo directory is the offline delivery unit.
