if [ "${CDS_ENABLE_FUNCTIONS:-1}" != "1" ]; then
    return
fi

FUNCTIONS_DIR=$CDS_ROOT/functions

# Load shell functions.
if [ -d "$FUNCTIONS_DIR" ]; then
    for file in $(find "$FUNCTIONS_DIR" -type f -name "*.sh"); do
        [ -r "$file" ] && source "$file"
    done
else
    echo "Warning: Functions directory not found!" >&2
fi

# Ensure data dir exists.
if [ ! -d "$CDS_DATA_DIR" ]; then
    mkdir -p "$CDS_DATA_DIR"
fi

# Init session state for memory mode.
if [[ "${CDS_MODE:-direct}" == "memory" ]]; then
    if declare -f _cds_init_session > /dev/null; then
        _cds_init_session
    fi
fi
