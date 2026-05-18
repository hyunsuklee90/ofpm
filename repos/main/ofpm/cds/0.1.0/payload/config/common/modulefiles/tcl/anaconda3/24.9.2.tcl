#%Module1.0

proc ModulesHelp { } {
    puts stderr "This module loads Anaconda3"
}

module-whatis "Name: Anaconda3"

# 공통 스크립트 불러오기
set common_script "$env(CDS_ROOT)/modulefunctions/tcl/setup_conda.tcl"

if {[file exists $common_script]} {
    source $common_script
    set conda_dir "/opt/anaconda3" 
    setup_conda $conda_dir
} else {
    puts stderr "Warning: Unable to load common Conda script!"
}
