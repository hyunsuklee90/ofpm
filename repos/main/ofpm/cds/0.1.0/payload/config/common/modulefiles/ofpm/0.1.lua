help([[ofpm environment loader]])
whatis([[Name : ofpm]])
whatis([[Version : 0.1]])
whatis([[Category : offline package manager]])
whatis([[Description : Sets OFPM_ROOT and PATH for ofpm-managed installs.]])

local root = os.getenv("OFPM_ROOT") or pathJoin(os.getenv("HOME"), ".ofpm")
local ollamaLib = pathJoin(root, "payloads", "ollama-runtime", "current", "lib", "ollama")
local ollamaModels = pathJoin(root, "data", "ollama-models")
local piConfig = pathJoin(root, "payloads", "pi-agent", "current", "config", "agent")

setenv("OFPM_ROOT", root)
prepend_path("PATH", pathJoin(root, "bin"))
for _, pkg in ipairs({"node-runtime", "pi-agent", "ollama-runtime"}) do
  local pkgBin = pathJoin(root, "payloads", pkg, "current", "bin")
  if isDir(pkgBin) then
    prepend_path("PATH", pkgBin)
  end
end
if isDir(pathJoin(root, "payloads", "pi-agent", "current", "config", "agent")) then
  setenv("PI_CODING_AGENT_DIR", piConfig)
end
if isDir(ollamaLib) then
  setenv("OLLAMA_LIBRARY_PATH", ollamaLib)
  prepend_path("LD_LIBRARY_PATH", ollamaLib)
end
if isDir(ollamaModels) then
  setenv("OLLAMA_MODELS", ollamaModels)
end
setenv("OFPM_OFFLINE_STRICT", os.getenv("OFPM_OFFLINE_STRICT") or "1")
