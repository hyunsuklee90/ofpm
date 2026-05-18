help([[
This module loads Anaconda3 env for OpenMC Version 0.15.2
]])

whatis("Name: Anaconda3/openmc-0.15.2")

local conda_dir = "/home/hyunsuk/.conda/envs/openmc-0.15.2"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)

prepend_path("PATH", pathJoin("/home/hyunsuk/.local/openmc-0.15.2", "bin"))
