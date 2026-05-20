# ofpm Overview

This document explains installation, runtime mode selection, repo registration, and the `apt` and `dnf` helper flows.

## 1. What ofpm Does

`ofpm` has two different roles:

- native package manager for `ofpm`-style packages under `repos/<name>/ofpm/...`
- offline repo helper for provider ecosystems like `apt` and `dnf`

That means:

- `ofpm install/remove/verify/...` are for `ofpm` packages
- `ofpm apt ...` and `ofpm dnf ...` help prepare offline provider repos
- actual provider installs still happen through `apt` or `dnf`

## 2. Runtime Modes

`ofpm` runs in one of two modes.

### Dev Mode

Dev mode is what you get when you run the source tree directly:

```bash
python3 -m ofpm ...
```

In dev mode:

- source root is the current checkout
- repo config lives under:

```text
<checkout>/config/repos.json
```

### Installed Mode

Installed mode is what you get when you run the installed launcher:

```bash
~/.ofpm/bin/ofpm ...
/opt/ofpm/bin/ofpm ...
```

In installed mode:

- source root is copied into `<managed-root>/src`
- repo config lives under `<managed-root>/config/repos.json`
- an empty `<managed-root>/repos/main` is created as a default local repo location

## 3. install-ofpm Layout

### User Install

```bash
python3 -m ofpm install-ofpm --root user
```

This creates:

```text
~/.ofpm/
|- bin/
|  `- ofpm
|- src/
|  `- ofpm/...
|- repos/
|  `- main/
`- config/
   `- repos.json
```

It also updates `~/.bashrc` with an `ofpm` block that:

- sets `OFPM_ROOT`
- prepends `~/.ofpm/bin` to `PATH`

### System Install

```bash
sudo python3 -m ofpm install-ofpm --root system
```

This creates:

```text
/opt/ofpm/
|- bin/
|  `- ofpm
|- src/
|  `- ofpm/...
|- repos/
|  `- main/
`- config/
   `- repos.json
```

It also writes:

- `/etc/profile.d/ofpm.sh`
- a source block into `/etc/bash.bashrc` or `/etc/bashrc`

### reinstall-ofpm

`reinstall-ofpm` is the force-reinstall form:

```bash
python3 -m ofpm reinstall-ofpm --root user
sudo python3 -m ofpm reinstall-ofpm --root system
```

## 4. What install-ofpm Installs

`install-ofpm` does not copy the entire dev checkout.

It installs:

- `<managed-root>/bin/ofpm`
- `<managed-root>/src/ofpm/...`
- `<managed-root>/repos/main`
- `<managed-root>/config/repos.json`

It also updates shell startup files:

- user install: `~/.bashrc`
- system install: `/etc/profile.d/ofpm.sh`
- system install interactive bash: `/etc/bash.bashrc` or `/etc/bashrc`

It intentionally excludes:

- `tests/`
- `.ai/`
- `docker/`
- `repos/`
- `config/`
- cache directories and `*.pyc`/`*.pyo`

The installed tree keeps the Python runtime and docs, then creates a fresh installed-side `repos/main` and `config/repos.json`.

## 5. Repo Registration

`ofpm` uses registered repos only.

Register a repo like this:

```bash
ofpm repo add main /some/path/to/repos/main
```

List the current registrations:

```bash
ofpm repo list
```

The config file used depends on mode:

- dev mode: `<checkout>/config/repos.json`
- installed mode: `<managed-root>/config/repos.json`

You can also override selection per command:

- `--repos-config <path>`
- `--repo <name>`
- `--repo-path <path>`

Resolution priority is:

1. `--repo-path`
2. `--repos-config` + optional `--repo`
3. default mode-specific `config/repos.json`

## 6. Native ofpm Package Flow

The normal `ofpm` package flow is:

```bash
ofpm list
ofpm show <package>
ofpm install <package>
ofpm verify <package>
ofpm remove <package>
```

Installed payloads live under the managed root:

```text
<managed-root>/payloads/<package>/<version>/
```

Current pointers live here:

```text
<managed-root>/payloads/<package>/current
```

Public executables are exposed under:

```text
<managed-root>/bin
```

So once the shell hook is active, `PATH` only needs the managed `bin/` directory.

## 7. Local Package and Repo Import Flow

There are two builder-side flows.

### Import a Local Project Path into a Repo

```bash
python3 -m ofpm repo import main \
  --path /some/project/output \
  --package demo \
  --version 1.0.0
```

This copies the local source path into:

```text
repos/main/ofpm/<package>/<version>/payload/
```

and writes:

```text
repos/main/ofpm/<package>/<version>/package.py
```

### Import an Existing package.py + payload/ Directory

```bash
python3 -m ofpm repo import-package main /some/packaging/ofpm
```

## 8. apt Helper Flow

`ofpm apt` is for:

- building a local apt repo
- activating that repo for target use

### Build Local Repo

```bash
ofpm apt build-repo zstd --output ./zstd-repo
ofpm apt source-line ./zstd-repo
```

This creates:

- `pool/`
- `Packages`
- `Packages.gz`

inside `./zstd-repo/`.

### Activate on Target

```bash
sudo ofpm apt activate ./zstd-repo
sudo apt install zstd
sudo ofpm apt deactivate ./zstd-repo
```

If a parent directory contains multiple built apt repos, you can register or remove them in one step:

```bash
sudo ofpm apt activate /opt/ofpm/repos/main/apt --recursive
sudo ofpm apt deactivate /opt/ofpm/repos/main/apt --recursive
```

## 9. dnf Helper Flow

`ofpm dnf`:

- build local rpm repo metadata
- write a `.repo` file
- let `dnf` do the real install

Example:

```bash
ofpm dnf build-repo offline-main /some/rpm/repo
sudo ofpm dnf activate offline-main /some/rpm/repo
sudo dnf install zstd
```

## 10. Recommended Practical Workflow

### Development

```bash
python3 -m ofpm ...
```

Use:

- checkout-local `config/repos.json`
- test fixture repos
- builder-side commands

### Personal Installed Usage

```bash
python3 -m ofpm install-ofpm --root user
source ~/.bashrc
ofpm repo add main /path/to/my/repo
ofpm list
```

### System Installed Usage

```bash
sudo python3 -m ofpm install-ofpm --root system
sudo ofpm repo add main /opt/ofpm/repos/main
ofpm list
```

### Provider Offline Helper Usage

```bash
ofpm apt build-repo zstd --output ./zstd-repo
sudo ofpm apt activate ./zstd-repo
sudo apt install zstd
```

- `ofpm` prepares offline repo state
- native package managers perform provider installs
