help([[
This module loads Anaconda3 env for nexus Monte Carlo Transport Code
]])

whatis("Name: Anaconda3/nexus")

setenv("CONDA_ROOT", "/opt/anaconda3")

local conda_dir = "/home/hyunsuk/.conda/envs/nexus"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)

local topdir = pathJoin(os.getenv("HOME"), ".local/nexus")
