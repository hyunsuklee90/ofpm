help([[
This module loads Anaconda3 env for AION Monte Carlo Transport Code
]])

whatis("Name: Anaconda3/aion")

setenv("CONDA_ROOT", "/opt/anaconda3")

local conda_dir = "/home/hyunsuk/.conda/envs/aion"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)

--prepend_path("PATH", pathJoin("/home/hyunsuk/codes/mccard", "bld"))
--prepend_path("PATH", pathJoin("/home/hyunsuk/.local/mccard", "bin"))
-- AION Monte Carlo Engine Module
local topdir = pathJoin(os.getenv("HOME"), ".local/aion")

-- prepend_path("PATH",            pathJoin(topdir, "../reference/codes/mcs/build/bin"))
-- prepend_path("PATH",            pathJoin(topdir, "../reference/codes/openmc/build/bin"))
-- prepend_path("PYTHONPATH",      pathJoin(topdir, "lib"))
-- prepend_path("LD_LIBRARY_PATH", pathJoin(topdir, "lib"))
