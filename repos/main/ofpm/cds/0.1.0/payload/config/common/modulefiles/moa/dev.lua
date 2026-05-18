help([[
This module loads Anaconda3 env for My Own Assitant
]])

whatis("Name: Anaconda3/moa")

setenv("CONDA_ROOT", "/opt/anaconda3")

local conda_dir = "/home/hyunsuk/.conda/envs/moa"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)

--prepend_path("PATH", pathJoin("/home/hyunsuk/codes/mccard", "bld"))
--prepend_path("PATH", pathJoin("/home/hyunsuk/.local/mccard", "bin"))
