help([[
This module loads Anaconda3 env for OpenMC developement forked from v0.15.2
]])

whatis("Name: Anaconda3/openmc")

setenv("CONDA_ROOT", "/opt/anaconda3")

local conda_dir = "/home/hyunsuk/.conda/envs/openmc"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)

prepend_path("PATH", pathJoin("/home/hyunsuk/.local/openmc", "bin"))
