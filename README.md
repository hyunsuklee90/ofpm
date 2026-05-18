# ofpm

Personal offline package manager scaffold with a portable repo snapshot model.

## Direction

- target-side usage should feel closer to a private offline `apt`/`yum`/`dnf`
- the main transfer unit is a portable repo directory, not a bundle archive
- builder-side commands prepare package content inside a repo
- target-side commands read from registered repos and remain offline-only

## Execution

During development, run directly from the repo with:

```bash
python3 -m ofpm ...
```

If installed with `pip`, the `ofpm` command is created automatically from the package entrypoint.

For a non-`pip` site install, generate a launcher script at the desired command path:

```bash
python3 -m ofpm install-cli /opt/ofpm/bin/ofpm
```

That launcher points at the current `ofpm` source tree and runs `python -m ofpm` with the correct `PYTHONPATH`.
If you omit the output path, `ofpm` creates `./ofpm` in the current directory when that path is free.

## Current Phase-1 Status

- `list`, `show`, `verify`, and `state` are implemented as working commands
- `node` supports a real phase-1 install/remove loop under a managed root
- `env` prints managed-root PATH setup for one-shot use or shell config
- `env package <pkg> --format modulefile` prints a modulefile on demand
- `source` manages local builder-side source paths
- `repo import` copies registered local sources into repo-managed package content
- `apt download` stores apt snapshots inside the repo
- `apt build-repo` turns a downloaded apt snapshot into an offline local apt repo
- `apt activate` writes a local apt source file for offline target use
- `dnf activate` writes a local dnf repo file for offline target use

## Repository Layout

- `ofpm/`: Python package code and CLI entrypoint
- `local/repos.json`: repo registration config
- `local/sources.json`: registered local source paths
- `repos/main/ofpm/<package>/<version>/package.py`: native ofpm package definition
- `repos/main/ofpm/<package>/<version>/payload/`: native ofpm package payload
- `repos/main/apt/<package>/<version>/package.py`: downloaded apt snapshot definition
- `repos/main/apt/<package>/<version>/payload/`: downloaded apt `.deb` payloads and provider metadata

## Core Concepts

- `source`: a local builder-side path registered with `ofpm source add`
- `provider snapshot`: downloaded metadata and payload set from an external provider such as `apt`
- `repo`: a portable directory tree that can be copied to another machine
- `package`: an installable unit defined by `package.py` plus `payload/`
- `state`: recorded installed package state under the managed root
- `receipt`: uninstall-oriented install record
- `ownership`: future basis for shared dependency tracking

## Quick Start

Initialize the local scaffold:

```bash
python3 -m ofpm init
```

Show registered repos:

```bash
python3 -m ofpm repo list
```

Install a non-`pip` launcher:

```bash
python3 -m ofpm install-cli /tmp/ofpm
/tmp/ofpm --help
```

List available packages from registered repos:

```bash
python3 -m ofpm list --verbose
```

Show package details:

```bash
python3 -m ofpm show ollama --files
```

Show installed state:

```bash
python3 -m ofpm state
python3 -m ofpm state --all-roots
python3 -m ofpm list --installed --all-roots
```

## Local Source Workflow

Register a local source directory:

```bash
python3 -m ofpm source add pi-tests /mnt/d/OneDrive/0project/harness/pi
python3 -m ofpm source show pi-tests
python3 -m ofpm source verify pi-tests
```

Import that source into the main repo as a package:

```bash
python3 -m ofpm repo import main \
  --source pi-tests \
  --package pi-tests \
  --version 1.0.0 \
  --profile ubuntu-22.04
```

That command copies the source into `repos/main/ofpm/<package>/<version>/payload/` and writes `package.py` beside it.

## Provider Repo Workflow

Inspect the host apt view:

```bash
python3 -m ofpm apt show zstd
python3 -m ofpm apt list zstd
```

Download an apt snapshot into the repo:

```bash
python3 -m ofpm apt download zstd
python3 -m ofpm apt show zstd --downloaded
```

Build a local apt repo from that snapshot:

```bash
python3 -m ofpm apt build-repo main zstd
python3 -m ofpm apt source-line main zstd
python3 -m ofpm apt commands main zstd --with-deps
```

Activate it on the target so native `apt` can use it directly:

```bash
sudo python3 -m ofpm apt activate main zstd
sudo apt install zstd
```

For dnf-style targets, write a repo file that points at a prepared local rpm repo:

```bash
sudo python3 -m ofpm dnf activate offline-main /opt/ofpm/repos/rpm/offline-main
sudo dnf install zstd
```

## Target Usage

Copy `repos/main` to the target machine, then register it:

```bash
ofpm repo add main /opt/ofpm/repos/main --scope user
```

Then use `ofpm` native packages like a normal offline package source:

```bash
ofpm list
ofpm show node
ofpm install node
```

## Managed Root State

Managed installs keep JSON state under:

```text
$HOME/.ofpm/state/
  installed/
  receipts/
  ownership/
  history.json
```

Show shell environment setup for managed tools:

```bash
python3 -m ofpm env --root user
eval "$(python3 -m ofpm env --root user --export)"
```

Show a package-specific shell snippet or modulefile text:

```bash
python3 -m ofpm env package pi-agent --root user
python3 -m ofpm env package pi-agent --root user --format modulefile
```

If the same package is installed in both roots, `remove` and `verify` require an explicit root:

```bash
python3 -m ofpm remove node --root user
sudo python3 -m ofpm remove node --root system
```

## Notes

- target-side commands are intended to remain offline-only
- builder-side commands such as `source`, `repo import`, and `apt download` prepare repo content
- `env` prints general managed-root setup; `env package` prints package-specific additions
- phase-1 install execution is real for the current built-in package types (`node`, `ollama`, `pi-agent`)
- generic imported package definitions already participate in `list`, `show`, and source verification, even where full install handlers are still evolving
