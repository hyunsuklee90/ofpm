help([[
This module loads Anaconda3 env for njoy16
]])

whatis("Name: Anaconda3/njoy")

setenv("CONDA_ROOT", "/opt/anaconda3")

local conda_dir = "/home/hyunsuk/.conda/envs/njoy"

local conda_util = loadfile(pathJoin(os.getenv("CDS_ROOT"), "modulefunctions/lua/conda_util.lua"))()

conda_util.setup(conda_dir)

--prepend_path("PATH", pathJoin("/home/hyunsuk/.local/njoy/NJOY2016", "bin"))
--prepend_path("LD_LIBRARY_PATH", pathJoin("/home/hyunsuk/.local/njoy/NJOY2016", "lib"))
--
--prepend_path("LD_LIBRARY_PATH", pathJoin("/home/hyunsuk/.local/njoy/ENDFtk", "lib"))
--prepend_path("PYTHONPATH", "/home/hyunsuk/.local/njoy/ENDFtk/lib/python3.11/site-packages")
--prepend_path("PYTHONPATH", "/home/hyunsuk/.local/njoy/ACEtk/lib/python3.11/site-packages")
--prepend_path("PYTHONPATH", "/home/hyunsuk/.local/njoy/dryad/lib/python3.11/site-packages")
