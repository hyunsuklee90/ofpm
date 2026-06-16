#!/bin/bash

export CDS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reset legacy installs that used CDS_HOME as the code root.
if [ -z "${CDS_HOME:-}" ] || [ "$CDS_HOME" = "$CDS_ROOT" ]; then
    export CDS_HOME="$HOME/.local/cds"
fi

export CDS_USER_CONFIG="$CDS_HOME/config.sh"
export CDS_ROOT_BASHRCD_DIR="$CDS_ROOT/bashrc.d"
export CDS_DATA_DIR="$CDS_HOME/data"

mkdir -p "$CDS_HOME" "$CDS_HOME/bashrc.d" "$CDS_HOME/modulefiles" "$CDS_DATA_DIR"

if [ ! -e "$CDS_USER_CONFIG" ]; then
    cat > "$CDS_USER_CONFIG" <<'EOF'
# Override CDS built-in shell features here if needed.
# export CDS_LOAD_BASHRCD=1
# export CDS_ENABLE_PROMPT=1
# export CDS_ENABLE_COLORS=1
# export CDS_ENABLE_ALIASES=1
# export CDS_ENABLE_FUNCTIONS=1
# export CDS_ENABLE_VIMRC=1
# export CDS_LABEL=""
#
# Theme selection
# export CDS_COLOR_THEME="default"
# export CDS_VIM_THEME="default"
#
# Modulefile search paths
# export CDS_MODULEPATHS="$CDS_ROOT/modulefiles/common:$CDS_HOME/modulefiles"
EOF
fi

if [ ! -e "$CDS_HOME/bashrc.sh" ]; then
    cat > "$CDS_HOME/bashrc.sh" <<'EOF'
# User shell overrides for CDS.
#
# User shell snippets in bashrc.d are loaded automatically.
for file in "$CDS_HOME/bashrc.d"/*.sh; do
    [ -r "$file" ] && source "$file"
done

# Personal shared layers from this CDS checkout.
# source "$CDS_ROOT/shared/common/bashrc.sh"
# source "$CDS_ROOT/shared/desktop/bashrc.sh"

# Personal shared modulefiles from this CDS checkout.
# if [ -d "$CDS_ROOT/shared/modulefiles" ] && module --version &> /dev/null; then
#     case ":${MODULEPATH:-}:" in
#         *":$CDS_ROOT/shared/modulefiles:"*) ;;
#         *) export MODULEPATH="${MODULEPATH:+$MODULEPATH:}$CDS_ROOT/shared/modulefiles" ;;
#     esac
# fi
EOF
fi

if [ -r "$CDS_USER_CONFIG" ]; then
    source "$CDS_USER_CONFIG"
fi

[[ $- != *i* ]] && return

export CDS_LOAD_BASHRCD="${CDS_LOAD_BASHRCD:-1}"
export CDS_ENABLE_PROMPT="${CDS_ENABLE_PROMPT:-1}"
export CDS_ENABLE_COLORS="${CDS_ENABLE_COLORS:-1}"
export CDS_ENABLE_ALIASES="${CDS_ENABLE_ALIASES:-1}"
export CDS_ENABLE_FUNCTIONS="${CDS_ENABLE_FUNCTIONS:-1}"
export CDS_ENABLE_VIMRC="${CDS_ENABLE_VIMRC:-1}"
export CDS_LABEL="${CDS_LABEL:-}"
export CDS_COLOR_THEME="${CDS_COLOR_THEME:-default}"
export CDS_VIM_THEME="${CDS_VIM_THEME:-default}"
export CDS_MODULEPATHS="${CDS_MODULEPATHS:-$CDS_ROOT/modulefiles/common:$CDS_HOME/modulefiles}"

# Load root shell modules.
if [ "$CDS_LOAD_BASHRCD" = "1" ]; then
    for file in "$CDS_ROOT_BASHRCD_DIR"/*.sh; do
        [ -r "$file" ] && source "$file"
    done
fi

# Load user shell config.
if [ -r "$CDS_HOME/bashrc.sh" ]; then
    source "$CDS_HOME/bashrc.sh"
fi

export PATH=.:$HOME/.local/bin:$PATH
