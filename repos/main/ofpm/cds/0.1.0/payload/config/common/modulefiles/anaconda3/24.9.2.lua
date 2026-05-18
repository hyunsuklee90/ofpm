help([[
This module loads Anaconda3-24.9.2
]])

whatis("Name: Anaconda3-24.9.2")
whatis("Conda_dir: /opt/anaconda3")

setenv("CONDA_ROOT", "/opt/anaconda3")

local conda_dir = "/opt/anaconda3"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)
