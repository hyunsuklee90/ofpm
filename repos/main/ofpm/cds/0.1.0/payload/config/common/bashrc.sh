if [ -n "${ONED:-}" ]; then
    export OPENMC_CROSS_SECTIONS="$ONED/xslib/OpenMC/endfb-viii.0-hdf5/cross_sections.xml"
fi

export LD_LIBRARY_PATH=/usr/local/lib/:$LD_LIBRARY_PATH
