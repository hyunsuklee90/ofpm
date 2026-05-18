help([[
This module loads Anaconda3 env for AionMC
]])

whatis("Name: Anaconda3/aionmc")

setenv("CONDA_ROOT", "/opt/anaconda3")

local conda_dir = "/home/hyunsuk/.conda/envs/aionmc"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)

--prepend_path("PATH", pathJoin("/home/hyunsuk/codes/mccard", "bld"))
--prepend_path("PATH", pathJoin("/home/hyunsuk/.local/mccard", "bin"))
