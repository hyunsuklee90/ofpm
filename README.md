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

For a non-`pip` install, install `ofpm` from the current source tree:

```bash
sudo python3 -m ofpm install-ofpm --root system
```

By default, a system install writes:

- `/opt/ofpm/bin/ofpm`
- `/opt/ofpm/src/` as the installed `ofpm` source tree
- `/opt/ofpm/repos/main` as the default local repo root
- `/opt/ofpm/config/repos.json` as the installed repo config
- `/etc/profile.d/ofpm.sh` for PATH and `OFPM_ROOT`
- a source block into `/etc/bash.bashrc` or `/etc/bashrc` for interactive bash shells

That launcher runs against the copied installed tree under `/opt/ofpm/src`, not the original dev checkout.

By default, a user install writes:

- `~/.ofpm/bin/ofpm`
- `~/.ofpm/src/` as the installed `ofpm` source tree
- `~/.ofpm/repos/main` as the default local repo root
- `~/.ofpm/config/repos.json` as the installed repo config
- an `ofpm` block into `~/.bashrc` for PATH and `OFPM_ROOT`

Refresh an existing install in place with:

```bash
python3 -m ofpm reinstall-ofpm --root user
sudo python3 -m ofpm reinstall-ofpm --root system
```

## Repository Layout

- `ofpm/`: Python package code and CLI entrypoint
- `config/repos.json`: repo registration config for the current dev checkout
- `docs/md/`: Markdown source documents
- `docs/html/`: generated HTML docs
- `docs/build_docs.py`: Markdown-to-HTML doc builder
- `repos/main/ofpm/<package>/<version>/package.py`: native ofpm package definition
- `repos/main/ofpm/<package>/<version>/payload/`: native ofpm package payload
- `repos/main/apt/<package>/<version>/package.py`: downloaded apt snapshot definition
- `repos/main/apt/<package>/<version>/payload/`: downloaded apt `.deb` payloads and provider metadata

## Core Concepts

- `local import path`: a builder-side path passed directly to `ofpm repo import --path`
- `provider snapshot`: downloaded metadata and payload set from an external provider such as `apt`
- `repo`: a portable directory tree that can be copied to another machine
- `package`: an installable unit defined by `package.py` plus `payload/`
- `state`: recorded installed package state under the managed root
- `receipt`: uninstall-oriented install record
- `ownership`: shared dependency tracking state

## Quick Start

Show registered repos:

```bash
python3 -m ofpm repo list
```

Install `ofpm` from the current source tree:

```bash
python3 -m ofpm install-ofpm --root user
source ~/.bashrc
ofpm --help
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

## Local Import Workflow

Import a local source path into the main repo as a package:

```bash
python3 -m ofpm repo import main \
  --path /mnt/d/OneDrive/0project/harness/pi \
  --package pi-tests \
  --version 1.0.0 \
  --profile ubuntu-22.04
```

That command copies the source into `repos/main/ofpm/<package>/<version>/payload/` and writes `package.py` beside it.

## Provider Repo Workflow

Inspect downloaded apt snapshots when needed:

```bash
python3 -m ofpm apt show zstd
python3 -m ofpm apt list
```

Build a local apt repo:

```bash
python3 -m ofpm apt build-repo zstd --output ./zstd-repo
python3 -m ofpm apt source-line ./zstd-repo
python3 -m ofpm apt commands zstd --output ./zstd-repo
```

Activate it on the target so native `apt` can use it directly:

```bash
sudo python3 -m ofpm apt activate ./zstd-repo
sudo apt install zstd
sudo python3 -m ofpm apt deactivate ./zstd-repo
```

If a parent directory contains multiple built apt repos, register or remove them all at once:

```bash
sudo python3 -m ofpm apt activate /opt/ofpm/repos/main/apt --recursive
sudo python3 -m ofpm apt deactivate /opt/ofpm/repos/main/apt --recursive
```

For dnf-style targets, write a repo file that points at a prepared local rpm repo:

```bash
sudo python3 -m ofpm dnf activate offline-main /opt/ofpm/repos/rpm/offline-main
sudo dnf install zstd
```

## Target Usage

Copy `repos/main` to the target machine, then register it:

```bash
ofpm repo add main /opt/ofpm/repos/main
```

Then use `ofpm` native packages:

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

## Docs

Markdown source lives under `docs/md/` and generated HTML lives under `docs/html/`.

Rebuild the HTML docs with:

```bash
python3 docs/build_docs.py
```

## Notes

- target-side commands are intended to remain offline-only
- builder-side commands such as `repo import`, `apt download`, and `dnf build-repo` prepare repo content
- `env` prints general managed-root setup; `env package` prints package-specific additions
