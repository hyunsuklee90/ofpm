# CDS layout, load order, and usage

This page explains how CDS is installed, where its files live, how configuration is loaded, and how to use `cds` after deployment.

## Hero Cards

### Code root
CDS_ROOT points to the shipped CDS files.
Examples: a repo checkout or `~/.local/cds/core`.

### User home
CDS_HOME points to the user-local CDS area.
Default: `~/.local/cds`.

### Built-in shell toggles
Core shell features default to enabled.
Override them in `~/.local/cds/config.sh` only when needed.

## Install layout

After a local install, the default layout is:

```text
~/.local/cds/
|- core/
|  |- bashrc.sh
|  |- bashrc.d/
|  |- functions/
|  |- legacy/
|  |- themes/
|  |- modulefiles/
|  |- modulefunctions/
|  `- docs/
|- config.sh
|- bashrc.sh
|- bashrc.d/
|- modulefiles/
`- data/
```

> Important: code and shipped defaults live under `core/`, while user config and runtime data live outside `core/`. This keeps updates and local state separate.

## Variables

- `CDS_ROOT`: the CDS code tree being sourced.
- `CDS_HOME`: the user-local CDS root. Default: `~/.local/cds`.
- `CDS_DATA_DIR`: user data directory. Default: `$CDS_HOME/data`.
- `CDS_USER_CONFIG`: user-wide CDS settings file.
- `CDS_ROOT_BASHRCD_DIR`: shipped shell module directory.
- `CDS_LOAD_BASHRCD`: load built-in shipped shell modules. Default: `1`.
- `CDS_ENABLE_PROMPT`: enable built-in prompt setup. Default: `1`.
- `CDS_ENABLE_COLORS`: enable built-in `LS_COLORS` setup. Default: `1`.
- `CDS_ENABLE_ALIASES`: enable built-in aliases. Default: `1`.
- `CDS_ENABLE_FUNCTIONS`: enable built-in shell function loading. Default: `1`.
- `CDS_ENABLE_VIMRC`: enable built-in `VIMINIT` setup. Default: `1`.
- `CDS_COLOR_THEME`: selects `themes/<name>/dir_colors`. Default: `default`.
- `CDS_VIM_THEME`: selects `themes/<name>/vimrc`. Default: `default`.
- `CDS_MODULEPATHS`: colon-separated modulefile search paths added by `bashrc.d/lmod.sh`.
- `CDS_LABEL`: optional prompt label.

## Load order

When you source `bashrc.sh`, CDS loads in this order:

1. Set `CDS_ROOT`, `CDS_HOME`, and `CDS_DATA_DIR`.
2. Source `$CDS_HOME/config.sh` if it exists.
3. Apply built-in default values for CDS shell feature toggles.
4. Source shipped shell modules from `$CDS_ROOT/bashrc.d/` when enabled.
5. Source user shell overrides from `$CDS_HOME/bashrc.sh` if present.

## User config flow

The main user settings entry point is `~/.local/cds/config.sh`.

Put global user overrides there. For example:

```bash
export CDS_LOAD_BASHRCD=1
export CDS_ENABLE_PROMPT=0
export CDS_ENABLE_COLORS=1
export CDS_COLOR_THEME="default"
export CDS_VIM_THEME="default"
export CDS_MODULEPATHS="$CDS_ROOT/modulefiles/common:$CDS_HOME/modulefiles"
export CDS_LABEL="desktop"
```

Then optional user shell overrides can live here:

```text
~/.local/cds/bashrc.sh
~/.local/cds/bashrc.d/*.sh
~/.local/cds/modulefiles/
```

This gives you three layers of user control:

- `config.sh` for built-in CDS shell feature toggles.
- `bashrc.sh` for the user shell entry file.
- `bashrc.d/*.sh` for user shell snippets that `bashrc.sh` loads by default.
- `modulefiles/` for user-local module definitions that you can include in `CDS_MODULEPATHS`.

The default user `bashrc.sh` template also includes commented examples for:

- sourcing personal shared layers from `$CDS_ROOT/shared/...`
- adding `$CDS_ROOT/shared/modulefiles` to `MODULEPATH`

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

- `$CDS_DATA_DIR/cds_db`
- `$CDS_DATA_DIR/cds_history`
- `$CDS_DATA_DIR/backups/`

## Recommended practice

- Keep CDS built-in defaults in `bashrc.d/` and related core files.
- Keep built-in themes under `themes/`.
- Keep shared modulefile sets under `modulefiles/` such as `modulefiles/common/`.
- Keep retired reference presets under `legacy/config/` if you still want them around for migration or manual copying.
- Keep personal shared layers under repo-owned paths such as `shared/` and source them from `~/.local/cds/bashrc.sh`.
- Keep personal overrides in `~/.local/cds/`.
- Keep runtime state in `~/.local/cds/data/`.
- Use repo source for development.
- Use `core/` installs for local deployment testing.
