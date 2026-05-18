#%Module1.0

proc setup_conda { conda_dir } {
    conflict anaconda

    prepend-path PATH "$conda_dir/bin"

    setenv CONDA_EXE "$conda_dir/bin/conda"
    setenv CONDA_PREFIX "$conda_dir"
    setenv CONDA_PYTHON_EXE "$conda_dir/bin/python"
    setenv ANACONDA_HOME "$conda_dir"
    setenv CONDA_SHLVL "0"

    # conda의 shell integration을 활성화
    setenv CONDA_ROOT "$conda_dir"
    setenv CONDA_ENV_PATH "$conda_dir/envs"
    setenv _CONDA_ROOT "$conda_dir"

    # conda initialize를 위해 conda.sh sourcing
    set bashrc_conda "$conda_dir/etc/profile.d/conda.sh"

    switch [module-info mode] {
        "load" {
        puts stderr "Anaconda3 has been loaded. ($conda_dir)"
        if { [file exists $bashrc_conda] } {
            system "source $bashrc_conda"
        }
        }

        "remove" {
        unsetenv CONDA_EXE
        unsetenv CONDA_PREFIX
        unsetenv CONDA_PYTHON_EXE
        unsetenv ANACONDA_HOME
        unsetenv CONDA_SHLVL
        unsetenv CONDA_ROOT
        unsetenv CONDA_ENV_PATH
        unsetenv _CONDA_ROOT

        remove-path PATH "$conda_dir/bin"

        puts stderr "Anaconda3 has been unloaded. ($conda_dir)"
        }
    }
}

