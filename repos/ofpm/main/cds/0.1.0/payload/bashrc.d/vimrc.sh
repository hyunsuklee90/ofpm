if [ "${CDS_ENABLE_VIMRC:-1}" != "1" ]; then
    return
fi

theme_file="$CDS_ROOT/themes/${CDS_VIM_THEME:-default}/vimrc"
if [ -f "$theme_file" ]; then
    export VIMINIT="set nocompatible | source ${theme_file}"
fi
