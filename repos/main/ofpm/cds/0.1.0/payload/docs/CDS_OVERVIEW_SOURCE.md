# CDS layout, load order, and usage

This page explains how CDS is installed, where its files live, how configuration is loaded, and how to use `cds` after deployment.

## Hero Cards

### Code root
CDS_ROOT points to the shipped CDS files.
Examples: a repo checkout or `~/.local/cds/core`.

### User home
CDS_HOME points to the user-local CDS area.
Default: `~/.local/cds`.

### Default shared layer
CDS_SHARED_CONFIGS defaults to `base`.
You can enable more shipped overlays later.

## Install layout

After a local install, the default layout is:

```text
~/.local/cds/
|- core/
|  |- bashrc.sh
|  |- bashrc.d/
|  |- functions/
|  |- config/
|  |- modulefunctions/
|  `- docs/
|- config/
|  |- config.sh
|  |- bashrc.sh
|  `- bashrc.d/
`- data/
```

> Important: code and shipped defaults live under `core/`, while user config and runtime data live outside `core/`. This keeps updates and local state separate.

## Variables

- `CDS_ROOT`: the CDS code tree being sourced.
- `CDS_HOME`: the user-local CDS root. Default: `~/.local/cds`.
- `CDS_CONFIG_DIR`: user config directory. Default: `$CDS_HOME/config`.
- `CDS_DATA_DIR`: user data directory. Default: `$CDS_HOME/data`.
- `CDS_USER_BASHRC`: user shell config file.
- `CDS_ROOT_BASHRCD_DIR`: shipped shell module directory.
- `CDS_USER_BASHRCD_DIR`: user shell module directory.
- `CDS_DATAPATH`: active data path. Default: `$CDS_DATA_DIR`.
- `CDS_SHARED_CONFIGS`: shipped config overlays to load. Default: `base`.
- `CDS_LOAD_ROOT_BASHRCD`: load shipped shell modules. Default: `1`.
- `CDS_LOAD_USER_BASHRCD`: load user shell modules. Default: `1`.
- `CDS_LABEL`: optional prompt label.

## Load order

When you source `bashrc.sh`, CDS loads in this order:

1. Set `CDS_ROOT`, `CDS_HOME`, `CDS_CONFIG_DIR`, and `CDS_DATA_DIR`.
2. Source `$CDS_CONFIG_DIR/config.sh` if it exists.
3. Apply default `CDS_SHARED_CONFIGS=base` if you did not override it.
4. Source shipped shell modules from `$CDS_ROOT/bashrc.d/` when enabled.
5. Source user shell modules from `$CDS_CONFIG_DIR/bashrc.d/` when enabled.
6. Source each shipped overlay from `$CDS_ROOT/config/<name>/bashrc.sh`.
7. Source user shell overrides from `$CDS_CONFIG_DIR/bashrc.sh` if present.

## User config flow

The main user entry point is `~/.local/cds/config/config.sh`.

Put global user overrides there. For example:

```bash
export CDS_LOAD_ROOT_BASHRCD=0
export CDS_LOAD_USER_BASHRCD=1
export CDS_SHARED_CONFIGS="base common"
export CDS_LABEL="desktop"
```

Then optional user shell overrides can live here:

```text
~/.local/cds/config/bashrc.sh
~/.local/cds/config/bashrc.d/*.sh
```

This gives you three layers of user control:

- `config.sh` for global settings and layer selection.
- `bashrc.sh` for a single user shell entry file.
- `bashrc.d/*.sh` for user shell modules such as aliases and prompt changes.

## Shared shipped configs

Directories under `$CDS_ROOT/config/` are shipped overlays. Right now the main default one is `base`.

You can enable more than one overlay by listing them in `CDS_SHARED_CONFIGS`:

```bash
export CDS_SHARED_CONFIGS="base common"
```

CDS will load them in order. This also applies to their `modulefiles/` directories.

> Shipped overlays are meant for reusable defaults and copied templates. User-specific changes should usually go in `~/.local/cds/config/`, not back into the shipped tree.

## Install and deployment

### Build an ofpm package

```bash
scripts/build-ofpm-package.sh 0.1.0
```

This creates `dist/ofpm-package-0.1.0/` with `package.py` and `payload/`.

### Local install without ofpm

```bash
./install-local.sh
```

This installs the current repo snapshot to `~/.local/cds/core` by default.

### Shell init

CDS does not edit `~/.bashrc` automatically. Add the source line yourself if needed:

```bash
source ~/.local/cds/core/bashrc.sh
```

## Using cds

Once CDS is loaded, the main command is `cds`.

```bash
cds -l
cds -a
cds -a /mnt/d/projects 10
cds -an 10 work
cds work
cds -z proj
cds -undo
```

Runtime data is stored here:

- `$CDS_DATAPATH/cds_db`
- `$CDS_DATAPATH/cds_history`
- `$CDS_DATAPATH/backups/`

## Recommended practice

- Keep reusable defaults in shipped overlays under `config/`.
- Keep personal overrides in `~/.local/cds/config/`.
- Keep runtime state in `~/.local/cds/data/`.
- Use repo source for development.
- Use `core/` installs for local deployment testing.
