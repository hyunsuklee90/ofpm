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
- `/opt/ofpm/repos/ofpm/main` as the default native repo root
- `/opt/ofpm/repos/ofpm/local-main` as the default large local repo root
- `/opt/ofpm/config/repos.json` as the installed repo config
- `/etc/profile.d/ofpm.sh` for PATH and `OFPM_ROOT`
- a source block into `/etc/bash.bashrc` or `/etc/bashrc` for interactive bash shells

That launcher runs against the copied installed tree under `/opt/ofpm/src`, not the original dev checkout.

By default, a user install writes:

- `~/.ofpm/bin/ofpm`
- `~/.ofpm/src/` as the installed `ofpm` source tree
- `~/.ofpm/repos/ofpm/main` as the default native repo root
- `~/.ofpm/repos/ofpm/local-main` as the default large local repo root
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
- `repos/ofpm/main/<package>/<version>/package.py`: native ofpm package definition
- `repos/ofpm/main/<package>/<version>/payload/`: native ofpm package payload
- `repos/ofpm/local-main/<package>/<version>/package.py`: large local native package definition
- `repos/ofpm/local-main/<package>/<version>/payload/`: large local native package payload
- `repos/apt/main/<package>/<version>/package.py`: downloaded apt snapshot definition
- `repos/apt/main/<package>/<version>/payload/`: downloaded apt `.deb` payloads and provider metadata

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

That command copies the source into `repos/ofpm/main/<package>/<version>/payload/` and writes `package.py` beside it.

Import a release archive into the main repo as a package:

```bash
python3 -m ofpm repo import-archive main \
  --archive /path/to/cds-0.1.0.tar.gz \
  --package cds \
  --version 0.1.0 \
  --profile ubuntu-22.04
```

If release metadata already exists, use `--meta` instead of repeating the fields:

```bash
python3 -m ofpm repo import-archive main \
  --archive /path/to/cds-0.1.0.tar.gz \
  --meta /path/to/ofpm.json
```

That command copies the archive into `repos/ofpm/main/<package>/<version>/payload/` and writes an archive-extract `package.py` beside it.

## Provider Repo Workflow

Build a local apt repo:

```bash
python3 -m ofpm apt
mkdir -p ./zstd-repo
cd ./zstd-repo
python3 -m ofpm apt build-repo zstd
python3 -m ofpm apt list .
python3 -m ofpm apt show zstd .
python3 -m ofpm apt source-line .
python3 -m ofpm apt commands zstd
```

`build-repo` writes `pool/`, `Packages`, and `Packages.gz` into the current directory by default. Use `--output <path>` only when you want a different repo root.
`apt list` and `apt show` inspect local apt repo metadata directly; they do not use `ofpm repo` registrations.

Activate it on the target so native `apt` can use it directly:

```bash
sudo python3 -m ofpm apt activate ./zstd-repo
sudo apt install zstd
sudo python3 -m ofpm apt deactivate ./zstd-repo
```

If a parent directory contains multiple built apt repos, register or remove them all at once:

```bash
sudo python3 -m ofpm apt activate /opt/ofpm/repos/apt/main --recursive
sudo python3 -m ofpm apt deactivate /opt/ofpm/repos/apt/main --recursive
```

For dnf-style targets, build metadata for a prepared rpm directory and then activate it:

```bash
python3 -m ofpm dnf build-repo /opt/ofpm/repos/rpm/offline-main
sudo python3 -m ofpm dnf activate /opt/ofpm/repos/rpm/offline-main
sudo dnf install zstd
sudo python3 -m ofpm dnf deactivate /opt/ofpm/repos/rpm/offline-main
```

If a parent directory contains multiple built dnf repos, register or remove them all at once:

```bash
sudo python3 -m ofpm dnf activate /opt/ofpm/repos/rpm --recursive
sudo python3 -m ofpm dnf deactivate /opt/ofpm/repos/rpm --recursive
```

## Target Usage

Copy `repos/ofpm/main` and any needed local repo directories to the target machine, then register them:

```bash
ofpm repo add main /opt/ofpm/repos/ofpm/main
ofpm repo add local-main /opt/ofpm/repos/ofpm/local-main
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
- builder-side commands such as `repo import`, `apt build-repo`, and `dnf build-repo` prepare repo content
- `env` prints general managed-root setup; `env package` prints package-specific additions
