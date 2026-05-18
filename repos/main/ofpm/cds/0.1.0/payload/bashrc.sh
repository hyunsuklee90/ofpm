#!/bin/bash

export CDS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reset legacy installs that used CDS_HOME as the code root.
if [ -z "${CDS_HOME:-}" ] || [ "$CDS_HOME" = "$CDS_ROOT" ]; then
    export CDS_HOME="$HOME/.local/cds"
fi

export CDS_CONFIG_DIR="$CDS_HOME/config"
export CDS_DATA_DIR="$CDS_HOME/data"
export CDS_USER_BASHRC="$CDS_CONFIG_DIR/bashrc.sh"
export CDS_ROOT_BASHRCD_DIR="$CDS_ROOT/bashrc.d"
export CDS_USER_BASHRCD_DIR="$CDS_CONFIG_DIR/bashrc.d"

mkdir -p "$CDS_USER_BASHRCD_DIR" "$CDS_DATA_DIR"

if [ ! -e "$CDS_CONFIG_DIR/config.sh" ]; then
    cat > "$CDS_CONFIG_DIR/config.sh" <<'EOF'
# User-wide CDS settings
export CDS_LOAD_ROOT_BASHRCD=1
export CDS_LOAD_USER_BASHRCD=1
export CDS_SHARED_CONFIGS="base"
export CDS_LABEL=""
EOF
fi

if [ -r "$CDS_CONFIG_DIR/config.sh" ]; then
    source "$CDS_CONFIG_DIR/config.sh"
fi

[[ $- != *i* ]] && return

export CDS_LOAD_ROOT_BASHRCD="${CDS_LOAD_ROOT_BASHRCD:-1}"
export CDS_LOAD_USER_BASHRCD="${CDS_LOAD_USER_BASHRCD:-1}"
export CDS_LABEL="${CDS_LABEL:-}"

export CDS_SHARED_CONFIGS="${CDS_SHARED_CONFIGS:-base}"
export CDS_DATAPATH="$CDS_DATA_DIR"

# Load root shell modules.
if [ "$CDS_LOAD_ROOT_BASHRCD" = "1" ]; then
    for file in "$CDS_ROOT_BASHRCD_DIR"/*.sh; do
        [ -r "$file" ] && source "$file"
    done
fi

# Load user shell modules.
if [ "$CDS_LOAD_USER_BASHRCD" = "1" ]; then
    for file in "$CDS_USER_BASHRCD_DIR"/*.sh; do
        [ -r "$file" ] && source "$file"
    done
fi

# Load shared config overlays.
for name in $CDS_SHARED_CONFIGS; do
    file="$CDS_ROOT/config/$name/bashrc.sh"
    [ -r "$file" ] && source "$file"
done

# Load user shell config.
if [ -r "$CDS_USER_BASHRC" ]; then
    source "$CDS_USER_BASHRC"
fi

export PATH=.:$HOME/.local/bin:$PATH
