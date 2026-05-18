from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofpm.package_def import load_package_file, load_package_hook
from ofpm.repo_data import find_installed_state, find_package_manifest, installed_states, managed_state_root, registered_repos
from ofpm.state_db import load_plugins_state, save_plugins_state


def project_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_repo_path(root: Path | None = None) -> Path:
    base = root or project_repo_root()
    return base / "repos" / "main"


def effective_registered_repos(root: Path | None = None) -> dict[str, str]:
    base = root or project_repo_root()
    repos = registered_repos(base)
    if repos:
        return repos
    return {"main": str(default_repo_path(base))}


def find_registered_package_manifest(package_id: str, version: str | None = None) -> Path | None:
    matches: list[tuple[str, Path]] = []
    for _, repo_path_raw in sorted(effective_registered_repos().items()):
        repo_path = Path(repo_path_raw).expanduser().resolve()
        manifest_path = find_package_manifest(repo_path, package_id, version)
        if manifest_path is None:
            continue
        data = load_package_file(manifest_path)
        matches.append((data["version"], manifest_path))
    if not matches:
        return None
    return sorted(matches, key=lambda item: item[0])[-1][1]


def managed_ollama_models_root(managed_root: Path) -> Path:
    return managed_root / "data" / "ollama-models"


def refresh_managed_ollama_models_store(managed_root: Path) -> dict[str, Any]:
    store_root = managed_ollama_models_root(managed_root)
    if store_root.exists():
        shutil.rmtree(store_root)

    installed = installed_states(managed_state_root(managed_root))
    model_states = [item for item in installed if item["package_id"].startswith("ollama-model-")]
    if not model_states:
        return {
            "store_root": str(store_root),
            "package_count": 0,
            "copied_files": 0,
        }

    store_root.mkdir(parents=True, exist_ok=True)
    copied_files = 0
    for item in model_states:
        models_path_raw = item["raw"]["package"].get("models_path")
        if not models_path_raw:
            continue
        models_path = Path(models_path_raw)
        if not models_path.exists():
            continue
        for path in sorted(models_path.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(models_path)
            destination = store_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.read_bytes() != path.read_bytes():
                    raise ValueError(f"shared ollama model store conflict for {destination}")
                continue
            shutil.copy2(path, destination)
            copied_files += 1
    return {
        "store_root": str(store_root),
        "package_count": len(model_states),
        "copied_files": copied_files,
    }


def list_attached_plugins(managed_root: Path, host_package_id: str) -> list[dict[str, Any]]:
    state = load_plugins_state(managed_root)
    return list(state.get("hosts", {}).get(host_package_id, {}).get("plugins", []))


def attach_plugin(managed_root: Path, host_package_id: str, plugin_package_id: str) -> dict[str, Any]:
    host_state = find_installed_state(managed_state_root(managed_root), host_package_id)
    if host_state is None:
        raise ValueError(f"host package not installed: {host_package_id}")
    plugin_state = find_installed_state(managed_state_root(managed_root), plugin_package_id)
    if plugin_state is None:
        raise ValueError(f"plugin package not installed: {plugin_package_id}")

    host_manifest = find_registered_package_manifest(host_package_id, host_state["package_version"])
    if host_manifest is None:
        raise ValueError(f"host package manifest not found: {host_package_id}@{host_state['package_version']}")
    host_data = load_package_file(host_manifest)
    allowed = {
        plugin["package_id"]: plugin
        for plugin in host_data.get("plugins", [])
        if plugin.get("package_id")
    }
    if plugin_package_id not in allowed:
        raise ValueError(f"plugin not supported by host package: {plugin_package_id}")

    state = load_plugins_state(managed_root)
    hosts = state.setdefault("hosts", {})
    host_entry = hosts.setdefault(host_package_id, {"plugins": []})
    plugins = [item for item in host_entry.get("plugins", []) if item.get("package_id") != plugin_package_id]
    plugins.append(
        {
            "package_id": plugin_package_id,
            "package_version": plugin_state["package_version"],
        }
    )
    host_entry["plugins"] = sorted(plugins, key=lambda item: item["package_id"])
    save_plugins_state(managed_root, state)
    return {
        "host_package_id": host_package_id,
        "plugin_package_id": plugin_package_id,
        "plugin_package_version": plugin_state["package_version"],
    }


def detach_plugin(managed_root: Path, host_package_id: str, plugin_package_id: str) -> dict[str, Any]:
    state = load_plugins_state(managed_root)
    hosts = state.setdefault("hosts", {})
    host_entry = hosts.setdefault(host_package_id, {"plugins": []})
    before = list(host_entry.get("plugins", []))
    host_entry["plugins"] = [item for item in before if item.get("package_id") != plugin_package_id]
    save_plugins_state(managed_root, state)
    return {
        "host_package_id": host_package_id,
        "plugin_package_id": plugin_package_id,
        "removed": len(before) != len(host_entry["plugins"]),
    }


@dataclass
class PluginRefreshContext:
    managed_root: Path
    package_manifest: Path
    package_data: dict[str, Any]
    root_kind: str
    installed_state: dict[str, Any]
    attached_plugins: list[dict[str, Any]]


def refresh_plugins(managed_root: Path, host_package_id: str | None = None) -> dict[str, Any]:
    installed = installed_states(managed_state_root(managed_root))
    plugins_state = load_plugins_state(managed_root)
    summary: dict[str, Any] = {
        "managed_root": str(managed_root),
        "refreshed_hosts": [],
        "notes": [],
    }

    model_refresh = refresh_managed_ollama_models_store(managed_root)
    if model_refresh["package_count"]:
        summary["notes"].append(
            f"rebuilt managed ollama model store from {model_refresh['package_count']} installed model package(s)"
        )

    installed_map = {item["package_id"]: item for item in installed}
    for package_id, host_entry in sorted(plugins_state.get("hosts", {}).items()):
        if host_package_id is not None and package_id != host_package_id:
            continue
        installed_host = installed_map.get(package_id)
        if installed_host is None:
            summary["notes"].append(f"skipped host refresh for {package_id}: host not installed")
            continue
        manifest_path = find_registered_package_manifest(package_id, installed_host["package_version"])
        if manifest_path is None:
            summary["notes"].append(f"skipped host refresh for {package_id}: manifest not found")
            continue
        hook = load_package_hook(manifest_path, "reconcile_plugins")
        if hook is None:
            continue
        package_data = load_package_file(manifest_path)
        ctx = PluginRefreshContext(
            managed_root=managed_root,
            package_manifest=manifest_path,
            package_data=package_data,
            root_kind=installed_host["raw"].get("root_kind", "user"),
            installed_state=installed_host,
            attached_plugins=list(host_entry.get("plugins", [])),
        )
        hook(ctx)
        summary["refreshed_hosts"].append(
            {
                "package_id": package_id,
                "package_version": installed_host["package_version"],
                "attached_plugins": list(host_entry.get("plugins", [])),
            }
        )
    return summary
