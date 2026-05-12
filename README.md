# ofpm

Personal offline package, bundle, and patch management scaffold.

CLI direction:

- primary command style follows `yum`/`dnf`
- selected wording may borrow from `apt`
- preferred command set is:
  - `list`
  - `show`
  - `install`
  - `upgrade`
  - `remove`
  - `verify`
  - `state`
  - `env`
  - `export`
  - `fetch apt`

Current phase-1 status:

- `list`, `show`, `verify`, and `state` are implemented as working commands
- `verify-source` performs heavier source artifact checks and is intended to be used less often
- `node-runtime` supports a real phase-1 install/remove loop under a managed root
- `env` prints managed-root PATH setup for one-shot use or shell config
- `export` creates a real offline transfer unit as a bundle directory or `tar.gz`
- `install`, `upgrade`, and `remove` currently print execution plans and decision context
- `fetch apt` currently prints builder-side acquisition plans
- lower-level bundle commands remain available for scaffold work:
  - `pack-full`
  - `pack-patch`
  - `apply`
  - `show-manifest`

Target vs builder split:

- target-side commands are intended to stay offline-only
- builder-side `fetch ...` commands are where online acquisition belongs
- default target policy assumes `OFPM_OFFLINE_STRICT=1`
- recommended transfer workflow is `ofpm export ...`, not manual file picking

Catalog visibility policy:

- `ofpm list` shows only packages whose referenced artifact sources currently exist
- `ofpm list --all` includes package definitions whose artifact sources are currently missing
- `ofpm show <package>` reports missing artifact sources explicitly
- actual artifact root paths are configured locally, outside Git-tracked package metadata
- deep source validation belongs in `ofpm verify-source <package>`, not in normal `list/show`

This repository is a minimal first-pass system for:

- content-addressed blob storage (`sha256`)
- full bundle export/import
- simple patch bundle export/import
- target profile metadata
- target machine state recording
- offline apply and verify flow

The initial implementation is intentionally conservative:

- package metadata is JSON
- bundle payloads are `.tar.gz`
- large files are stored as complete blobs, not binary diffs
- patch bundles replace changed files and remove deleted files
- state is recorded from the applied bundle and verified against target files

## Repository Layout

- `src/ofpm/`: CLI implementation
- `scripts/ofpm.py`: runnable entrypoint
- `schemas/`: JSON schema drafts for package, bundle, profile, and state
- `profiles/`: sample target profiles
- `catalog/packages/`: package definitions and payload sources
- `store/blobs/`: content-addressed blob store
- `dist/`: exported bundle archives
- `runtime/`: sample runtime target roots and state files

## Core Concepts

- `package`: desired file layout for one installable unit
- `full bundle`: complete install/update payload for a package version
- `patch bundle`: delta from one package version to another
- `profile`: target machine family metadata such as `ubuntu-22.04` or `rocky-9`
- `state`: recorded applied bundle and resulting tracked files for one target root

## Quick Start

Use the local wrapper directly:

```bash
./bin/ofpm list --verbose
```

Optional shell alias:

```bash
alias ofpm='/mnt/d/OneDrive/0project/ofpm/bin/ofpm'
```

Show configured artifact roots:

```bash
./bin/ofpm sources
```

Initialize working directories:

```bash
./bin/ofpm init
```

List available packages from the local catalog:

```bash
./bin/ofpm list --verbose
```

Show package details:

```bash
./bin/ofpm show ollama-runtime --files
```

Show installed state:

```bash
./bin/ofpm state
```

Install `node-runtime` into a test managed root:

```bash
./bin/ofpm install node-runtime --root-path /tmp/ofpm-user-root
./bin/ofpm state --root-path /tmp/ofpm-user-root
./bin/ofpm verify node-runtime --root-path /tmp/ofpm-user-root
```

Remove it again:

```bash
./bin/ofpm remove node-runtime --root-path /tmp/ofpm-user-root
```

Show the PATH setup needed to prefer `ofpm`-managed tools:

```bash
./bin/ofpm env --root user
eval "$(./bin/ofpm env --root user --export)"
```

Create an offline bundle directory from selected packages:

```bash
./bin/ofpm export pi-stack \
  --package node-runtime \
  --package ollama-runtime \
  --package ollama-model-gemma4-e4b \
  --package pi-agent \
  --format dir
```

Create an offline bundle archive:

```bash
./bin/ofpm export pi-stack \
  --package node-runtime \
  --package ollama-runtime \
  --package ollama-model-gemma4-e4b \
  --package pi-agent \
  --format tar.gz
```

Show an online acquisition plan for an apt package:

```bash
./bin/ofpm fetch apt curl --distro ubuntu --release 22.04 --arch amd64 --with-deps
```

Verify an installed package against recorded state:

```bash
./bin/ofpm verify pi-agent --target-root "$HOME/.ofpm"
```

Run a deeper source artifact check:

```bash
./bin/ofpm verify-source pi-agent
```

Build a full bundle:

```bash
./bin/ofpm pack-full \
  --package catalog/packages/ollama-runtime/0.23.2/package.json
```

Build a patch bundle:

```bash
# requires two real versions of the same package lineage
# example to be refreshed when the first non-demo upgrade pair is added
```

Apply a bundle to a target root:

```bash
./bin/ofpm apply \
  --bundle dist/ollama-runtime-0.23.2-full.tar.gz \
  --target-root runtime/targets/example-root \
  --state runtime/state/example-root.json
```

Verify recorded state:

```bash
./bin/ofpm verify-state \
  --target-root runtime/targets/example-root \
  --state runtime/state/example-root.json
```

If the target root is on a filesystem that does not preserve POSIX modes reliably
(for example a Windows-mounted path under WSL), use default hash-only verification.
Use `--strict-modes` only on targets where file mode preservation is meaningful.

## Design Notes

- Bundle archives embed `bundle.json` plus only the blobs required for that bundle.
- The local `store/blobs/` directory acts as the long-lived CAS store for source ingestion.
- `apply` verifies bundle blob hashes before writing target files.
- `verify-state` verifies current target contents against recorded state.
- If a machine drifts too far from a known base version, a full bundle should be used instead of a patch.

## Near-Term Extensions

- multi-package bundle composition
- explicit prerequisites and upgrade graph rules
- conda env snapshots and windows installer handlers
- model/blob validators like manifest-to-blob closure checks for Ollama-style assets
- signed manifests and stronger provenance metadata
