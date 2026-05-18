if module --version &> /dev/null; then
    for name in $CDS_SHARED_CONFIGS; do
        dir="$CDS_ROOT/config/$name/modulefiles"
        if [ -d "$dir" ] && [[ ":$MODULEPATH:" != *":$dir:"* ]]; then
            export MODULEPATH=$MODULEPATH:$dir
        fi
    done
    dir="$CDS_USER_PROFILE_DIR/modulefiles"
    if [ -d "$dir" ] && [[ ":$MODULEPATH:" != *":$dir:"* ]]; then
        export MODULEPATH=$MODULEPATH:$dir
    fi
fi
