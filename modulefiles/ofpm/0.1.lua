help([[ofpm environment loader]])
whatis([[Name : ofpm]])
whatis([[Version : 0.1]])
whatis([[Category : offline package manager]])
whatis([[Description : Sets OFPM_ROOT and PATH for ofpm-managed installs.]])

local root = os.getenv("OFPM_ROOT") or pathJoin(os.getenv("HOME"), ".ofpm")

setenv("OFPM_ROOT", root)
prepend_path("PATH", pathJoin(root, "bin"))
setenv("OFPM_OFFLINE_STRICT", os.getenv("OFPM_OFFLINE_STRICT") or "1")
