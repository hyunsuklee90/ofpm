from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ofpm.recipes import OfpmRecipe
from ofpm.package_def import load_package_file
from ofpm.repo_data import find_package_manifest, installed_states
from ofpm.runtime_support import (
    expose_public_executables,
    find_installed_state,
    managed_state_root,
    package_files_by_target,
    record_install,
    remove_managed_payload,
    required_dependency_errors,
    reset_current_link,
    resolve_source_path,
    utc_now,
)
from ofpm.state_db import dump_json


class Recipe(OfpmRecipe):
    def __init__(self):
        super().__init__(
            package_id="pi-agent",
            version="0.74.0",
            target={"os": "linux", "distro": "ubuntu", "release": "22.04", "arch": "amd64"},
            install_root="payloads/pi-agent/0.74.0",
            depends=[
                {
                    "package_id": "node",
                    "version": "24.13.1",
                    "reason": "pi-agent is distributed as a Node-based CLI",
                }
            ],
            plugins=[
                {
                    "package_id": "ollama",
                    "version": "0.23.2",
                    "reason": "optional local LLM provider for pi-agent",
                },
            ],
            metadata={
                "description": "offline pi tgz, npm cache, and helper binaries stored inside repos/main",
                "source_kind": "repo-internal",
                "origin_relroot": "packages/pi-agent/0.74.0/payload",
            },
            env={
                "set": {"PI_CODING_AGENT_DIR": "@config_dir"},
                "prepend_path": {"PATH": ["@package_root/bin"]},
            },
            files=[
                {"source": "payload/archives/earendil-works-pi-coding-agent-0.74.0.tgz", "target": "archives/earendil-works-pi-coding-agent-0.74.0.tgz", "mode": "0644"},
                {"source": "payload/bin/rg", "target": "bin/rg", "mode": "0755"},
                {"source": "payload/bin/fd", "target": "bin/fd", "mode": "0755"},
                {"source_dir": "payload/npm-cache", "target_dir": "npm-cache", "file_count_hint": 1004, "mode": "0644"},
            ],
        )

    def _default_models_config(self) -> dict:
        return {"providers": {}}

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _ollama_provider_from_installed_models(self, managed_root: Path) -> dict | None:
        installed = installed_states(managed_state_root(managed_root))
        runtime = next((item for item in installed if item["package_id"] in {"ollama", "ollama-runtime"}), None)
        if runtime is None:
            return None

        repo_root = self._repo_root()
        models: list[dict[str, str]] = []
        for item in installed:
            if not item["package_id"].startswith("ollama-model-"):
                continue
            manifest_path = find_package_manifest(repo_root, item["package_id"], item["package_version"])
            if manifest_path is None:
                continue
            manifest = load_package_file(manifest_path)
            pi_model = manifest.get("metadata", {}).get("pi_model")
            if not pi_model:
                continue
            models.append({"id": pi_model["id"], "name": pi_model["name"]})

        return {
            "baseUrl": "http://localhost:11434/v1",
            "api": "openai-completions",
            "apiKey": "ollama",
            "compat": {
                "supportsDeveloperRole": False,
                "supportsReasoningEffort": False,
            },
            "models": sorted(models, key=lambda item: item["id"]),
        }

    def _reconcile_models_config(self, managed_root: Path, *, enable_ollama: bool) -> None:
        installed = installed_states(managed_state_root(managed_root))
        pi_state = next((item for item in installed if item["package_id"] == "pi-agent"), None)
        if pi_state is None:
            return

        config_dir = Path(pi_state["raw"]["package"]["config_dir"])
        config_path = config_dir / "models.json"
        config = self._default_models_config()
        if enable_ollama:
            ollama_provider = self._ollama_provider_from_installed_models(managed_root)
            if ollama_provider is not None:
                config["providers"]["ollama"] = ollama_provider
        dump_json(config_path, config)

    def reconcile_plugins(self, runtime) -> None:
        attached = {item["package_id"] for item in runtime.attached_plugins}
        self._reconcile_models_config(runtime.managed_root, enable_ollama=bool({"ollama", "ollama-runtime"} & attached))

    def install(self, runtime):
        package_data = runtime.package_data
        package_id = package_data["package_id"]
        version = package_data["version"]
        version_root = runtime.managed_root / "payloads" / package_id / version

        dependency_errors = required_dependency_errors(runtime.managed_root, package_data)
        if dependency_errors:
            raise ValueError("; ".join(dependency_errors))

        node_state = None
        for package_id in ["node", "node-runtime"]:
            node_state = find_installed_state(managed_state_root(runtime.managed_root), package_id)
            if node_state is not None:
                break
        if node_state is None:
            raise ValueError("node must be installed before pi-agent")

        node_current = Path(node_state["raw"]["package"]["current_path"])
        npm_path = node_current / "bin" / "npm"
        if not npm_path.exists():
            raise FileNotFoundError(f"missing npm executable: {npm_path}")
        if version_root.exists():
            raise FileExistsError(f"package version already installed at {version_root}")

        files = package_files_by_target(package_data, runtime.package_manifest, artifact_roots=runtime.artifact_roots)
        tgz_source = files.get("archives/earendil-works-pi-coding-agent-0.74.0.tgz")
        rg_source = files.get("bin/rg")
        fd_source = files.get("bin/fd")
        cache_item = next(item for item in package_data["files"] if "source_dir_relpath" in item or "source_dir" in item)
        npm_cache_source = resolve_source_path(
            package_data,
            runtime.package_manifest,
            cache_item,
            key="source_dir",
            artifact_roots=runtime.artifact_roots,
        )
        if tgz_source is None:
            raise FileNotFoundError("pi-agent requires tgz source")

        runtime.managed_root.mkdir(parents=True, exist_ok=True)
        version_root.mkdir(parents=True, exist_ok=False)
        prefix_root = version_root / "prefix"
        config_dir = version_root / "config" / "agent"
        bin_dir = version_root / "bin"
        prefix_root.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="ofpm-npm-cache-") as temp_cache:
            temp_cache_root = Path(temp_cache)
            shutil.copytree(npm_cache_source, temp_cache_root, dirs_exist_ok=True)
            env = os.environ.copy()
            env["PATH"] = f"{node_current / 'bin'}:{env.get('PATH', '')}"
            env["PI_CODING_AGENT_DIR"] = str(config_dir)
            subprocess.run(
                [
                    str(npm_path),
                    "install",
                    "-g",
                    "--offline",
                    "--cache",
                    str(temp_cache_root),
                    "--prefix",
                    str(prefix_root),
                    str(tgz_source),
                ],
                check=True,
                env=env,
            )

        installed_pi = prefix_root / "bin" / "pi"
        if not installed_pi.exists():
            raise FileNotFoundError(f"missing installed pi binary: {installed_pi}")

        current_link = version_root.parent / "current"
        reset_current_link(current_link, version_root)
        reset_current_link(bin_dir / "pi", installed_pi)
        if rg_source and rg_source.exists():
            shutil.copy2(rg_source, bin_dir / "rg")
            os.chmod(bin_dir / "rg", 0o755)
        if fd_source and fd_source.exists():
            shutil.copy2(fd_source, bin_dir / "fd")
            os.chmod(bin_dir / "fd", 0o755)
        dump_json(config_dir / "models.json", self._default_models_config())
        executables = [
            str(current_link / "bin" / "pi"),
            str(current_link / "bin" / "rg"),
            str(current_link / "bin" / "fd"),
        ]
        public_executables = expose_public_executables(runtime.managed_root, executables)

        state = {
            "schema_version": "1",
            "updated_at": utc_now(),
            "install_type": "managed-install",
            "root_kind": runtime.root_kind,
            "managed_root": str(runtime.managed_root),
            "package": {
                "package_id": package_id,
                "package_version": version,
                "profile_id": package_data["profile_id"],
                "install_root": package_data["install_root"],
                "description": package_data.get("metadata", {}).get("description", ""),
                "env": package_data.get("env", {}),
                "version_root": str(version_root),
                "current_path": str(current_link),
                "prefix_root": str(prefix_root),
                "config_dir": str(config_dir),
                "executables": executables,
                "public_executables": public_executables,
                "node_runtime_path": str(node_current),
                "source_artifacts": [str(tgz_source), str(npm_cache_source)],
            },
        }
        record_install(
            runtime.managed_root,
            state,
            provider="ofpm-native",
            strategy="offline-npm-prefix",
            managed_objects={
                "version_root": str(version_root),
                "current_path": str(current_link),
                "executables": state["package"]["executables"],
                "config_dir": str(config_dir),
                "prefix_root": str(prefix_root),
            },
            artifact_ref={"type": "source-artifacts", "paths": state["package"]["source_artifacts"]},
        )
        return state

    def verify(self, runtime):
        errors: list[str] = []
        package = (runtime.installed_state or {}).get("raw", {}).get("package", {})
        config_dir = Path(package.get("config_dir", ""))
        for executable in package.get("executables", []):
            path = Path(executable)
            if not path.exists():
                errors.append(f"missing executable: {path}")
                continue
            if not os.access(path, os.X_OK):
                errors.append(f"not executable: {path}")

        models_json = config_dir / "models.json"
        if not models_json.exists():
            errors.append(f"missing config file: {models_json}")

        executables = package.get("executables", [])
        if executables:
            pi_path = Path(executables[0])
            node_runtime_path = Path(package.get("node_runtime_path", ""))
            env = os.environ.copy()
            env["PI_CODING_AGENT_DIR"] = str(config_dir)
            env["PATH"] = f"{node_runtime_path / 'bin'}:{pi_path.parent}:{env.get('PATH', '')}"
            result = subprocess.run(
                [str(pi_path), "--help"],
                env=env,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                errors.append(f"pi --help failed: {result.stderr.strip() or result.stdout.strip()}")
        return errors

    def remove(self, runtime):
        return remove_managed_payload(runtime.managed_root, runtime.installed_state or {})


RECIPE = Recipe()
