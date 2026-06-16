if module --version &> /dev/null; then
    old_ifs="$IFS"
    IFS=':'
    for dir in $CDS_MODULEPATHS; do
        [ -z "$dir" ] && continue
        if [ -d "$dir" ] && [[ ":${MODULEPATH:-}:" != *":$dir:"* ]]; then
            export MODULEPATH="${MODULEPATH:+$MODULEPATH:}$dir"
        fi
    done
    IFS="$old_ifs"
fi
