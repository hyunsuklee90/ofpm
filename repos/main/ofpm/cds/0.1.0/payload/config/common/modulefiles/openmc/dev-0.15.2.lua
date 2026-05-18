help([[
This module loads Anaconda3 env for OpenMC developement forked from v0.15.2
]])

whatis("Name: Anaconda3/openmc-dev-0.15.2")

setenv("CONDA_ROOT", "/opt/anaconda3")

local conda_dir = "/home/hyunsuk/.conda/envs/openmc-dev-0.15.2"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)

prepend_path("PATH", pathJoin("/home/hyunsuk/.local/openmc-dev-0.15.2", "bin"))
