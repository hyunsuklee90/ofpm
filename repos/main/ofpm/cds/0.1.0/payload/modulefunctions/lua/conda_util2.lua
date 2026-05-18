local conda_util = {}

function conda_util.setup(conda_dir)
    family("anaconda")

    prepend_path("PATH", pathJoin(conda_dir, "bin"))

    setenv("CONDA_EXE", pathJoin(conda_dir, "bin", "conda"))
    setenv("CONDA_PREFIX", conda_dir)
    setenv("CONDA_PYTHON_EXE", pathJoin(conda_dir, "bin", "python"))
    setenv("ANACONDA_HOME", conda_dir)
    setenv("CONDA_SHLVL", "0")

    local bash_init_script = pathJoin(conda_dir, "etc", "profile.d", "conda.sh")
    if isFile(bash_init_script) then
        execute{cmd="source " .. bash_init_script, modeA={"load"}}
    end

    if mode() == "load" then
        io.stderr:write("Anaconda3 has been loaded.")
        io.stderr:write(" (condadir: "..conda_dir..")\n")
    end

    if mode() == "unload" then
        -- Conda 환경 비활성화 시도
        if isFile(bash_init_script) then
            execute{cmd="source " .. bash_init_script .. " && conda deactivate", modeA={"unload"}}
        end

        -- 환경 변수 제거
        local conda_vars = {"CONDA_EXE", "CONDA_PREFIX", "CONDA_PYTHON_EXE", "ANACONDA_HOME", "CONDA_SHLVL"}
        for _, var in ipairs(conda_vars) do
            unsetenv(var)
        end

        -- PATH에서 anaconda 경로 제거
        remove_path("PATH", pathJoin(conda_dir, "bin"))

        io.stderr:write("Anaconda3 has been unloaded.")
        io.stderr:write(" (condadir: "..conda_dir..")\n")
    end
end


return conda_util
