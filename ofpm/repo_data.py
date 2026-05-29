from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ofpm.package_def import load_package_file
from ofpm.state_db import managed_installed_state_root


def load_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def user_config_root() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return Path(xdg).expanduser() / "ofpm"
    return Path.home() / ".config" / "ofpm"


def repo_local_config_root(repo_root: Path) -> Path:
    installed_home = os.environ.get("OFPM_HOME", "").strip()
    if installed_home:
        return Path(installed_home).expanduser().resolve() / "config"
    return repo_root / "config"


def repo_repos_config_path(repo_root: Path) -> Path:
    return repo_local_config_root(repo_root) / "repos.json"


def legacy_artifact_roots_path(repo_root: Path) -> Path:
    return repo_local_config_root(repo_root) / "artifact-roots.json"


def load_artifact_roots(repo_root: Path) -> dict[str, str]:
    artifact_roots: dict[str, str] = {}
    config_path = legacy_artifact_roots_path(repo_root)
    if config_path.exists():
        artifact_roots.update(load_json(config_path))

    prefix = "OFPM_ARTIFACT_ROOT_"
    for key, value in os.environ.items():
        if key.startswith(prefix):
            root_id = key[len(prefix) :].lower().replace("_", "-")
            artifact_roots[root_id] = value
    return artifact_roots


def save_repos_config(path: Path, repos: dict[str, str]) -> None:
    dump_json(path, dict(sorted(repos.items())))


def is_valid_native_package_manifest(manifest_path: Path) -> bool:
    try:
        data = load_package_file(manifest_path)
    except Exception:
        return False
    required = ["package_id", "version", "install_root", "files"]
    return all(key in data for key in required)


def is_native_repo_package_root(path: Path) -> bool:
    for manifest_path in sorted(path.glob("*/*/package.py")):
        if is_valid_native_package_manifest(manifest_path):
            return True
    for manifest_path in sorted(path.glob("*/*/package.json")):
        if is_valid_native_package_manifest(manifest_path):
            return True
    return False


def native_repo_package_root(repo_root: Path) -> Path:
    if is_native_repo_package_root(repo_root):
        return repo_root
    candidate = repo_root / "ofpm"
    if is_native_repo_package_root(candidate):
        return candidate
    legacy = repo_root / "catalog" / "packages"
    if is_native_repo_package_root(legacy):
        return legacy
    return candidate


def repo_package_manifests(repo_root: Path) -> list[Path]:
    package_dir = native_repo_package_root(repo_root)
    results = sorted(package_dir.glob("*/*/package.py"))
    if results:
        return results
    return sorted(package_dir.glob("*/*/package.json"))


def registered_repos(repo_root: Path, config_path: Path | None = None) -> dict[str, str]:
    path = config_path or repo_repos_config_path(repo_root)
    if not path.exists():
        return {}
    return dict(sorted(load_json(path).items()))


def resolve_artifact_root(package_data: dict[str, Any], artifact_roots: dict[str, str] | None) -> Path | None:
    root_id = package_data.get("metadata", {}).get("artifact_root_id")
    if not root_id:
        return None
    roots = artifact_roots or {}
    configured = roots.get(root_id)
    if not configured:
        return None
    return Path(configured).expanduser().resolve()


def package_root_from_manifest(package_manifest: Path) -> Path:
    return package_manifest.parent


def resolve_source_path(
    package_data: dict[str, Any],
    package_manifest: Path,
    item: dict[str, Any],
    *,
    key: str,
    artifact_roots: dict[str, str] | None = None,
) -> Path:
    package_root = package_root_from_manifest(package_manifest)
    if key in item:
        return (package_root / item[key]).resolve()

    rel_key = f"{key}_relpath"
    if rel_key in item:
        artifact_root = resolve_artifact_root(package_data, artifact_roots)
        if artifact_root is None:
            root_id = package_data.get("metadata", {}).get("artifact_root_id", "<unset>")
            raise ValueError(
                f"artifact root not configured for package {package_data['package_id']} "
                f"(artifact_root_id={root_id})"
            )
        return (artifact_root / item[rel_key]).resolve()

    raise ValueError(f"missing source path key: expected {key} or {rel_key}")


def count_package_entries(
    package_data: dict[str, Any],
    package_manifest: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> int:
    total = 0
    for item in package_data["files"]:
        if ("source" in item or "source_relpath" in item) and "target" in item:
            total += 1
            continue
        if ("source_dir" in item or "source_dir_relpath" in item) and "target_dir" in item:
            if "file_count_hint" in item:
                total += int(item["file_count_hint"])
                continue
            source_dir = resolve_source_path(
                package_data,
                package_manifest,
                item,
                key="source_dir",
                artifact_roots=artifact_roots,
            )
            if not source_dir.exists():
                continue
            total += sum(1 for path in source_dir.rglob("*") if path.is_file())
            continue
        raise ValueError(
            "file items must define either source/source_relpath + target "
            "or source_dir/source_dir_relpath + target_dir"
        )
    return total


def collect_declared_source_paths(
    package_data: dict[str, Any],
    package_manifest: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> list[str]:
    paths: list[str] = []
    for item in package_data["files"]:
        if ("source" in item or "source_relpath" in item) and "target" in item:
            source = resolve_source_path(
                package_data,
                package_manifest,
                item,
                key="source",
                artifact_roots=artifact_roots,
            )
            paths.append(str(source))
            continue
        if ("source_dir" in item or "source_dir_relpath" in item) and "target_dir" in item:
            source_dir = resolve_source_path(
                package_data,
                package_manifest,
                item,
                key="source_dir",
                artifact_roots=artifact_roots,
            )
            paths.append(str(source_dir))
            continue
    return paths


def collect_missing_sources(
    package_data: dict[str, Any],
    package_manifest: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> list[str]:
    missing: list[str] = []
    for item in package_data["files"]:
        if ("source" in item or "source_relpath" in item) and "target" in item:
            source = resolve_source_path(
                package_data,
                package_manifest,
                item,
                key="source",
                artifact_roots=artifact_roots,
            )
            if not source.exists():
                missing.append(str(source))
            continue
        if ("source_dir" in item or "source_dir_relpath" in item) and "target_dir" in item:
            source_dir = resolve_source_path(
                package_data,
                package_manifest,
                item,
                key="source_dir",
                artifact_roots=artifact_roots,
            )
            if not source_dir.exists():
                missing.append(str(source_dir))
            continue
    return missing


def expanded_package_entries(
    package_data: dict[str, Any],
    package_manifest: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in package_data["files"]:
        if ("source" in item or "source_relpath" in item) and "target" in item:
            source = resolve_source_path(
                package_data,
                package_manifest,
                item,
                key="source",
                artifact_roots=artifact_roots,
            )
            entries.append(
                {
                    "source": str(source),
                    "target": item["target"].replace("\\", "/"),
                    "mode": item.get("mode"),
                }
            )
            continue

        if ("source_dir" in item or "source_dir_relpath" in item) and "target_dir" in item:
            source_dir = resolve_source_path(
                package_data,
                package_manifest,
                item,
                key="source_dir",
                artifact_roots=artifact_roots,
            )
            target_dir = item["target_dir"].strip("/").replace("\\", "/")
            if not source_dir.exists():
                continue
            for path in sorted(source_dir.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(source_dir).as_posix()
                target = "/".join(part for part in [target_dir, relative] if part)
                entries.append(
                    {
                        "source": str(path),
                        "target": target,
                        "mode": item.get("mode"),
                    }
                )
            continue

        raise ValueError(
            "file items must define either source/source_relpath + target "
            "or source_dir/source_dir_relpath + target_dir"
        )
    return entries


def package_summary_from_manifest(
    manifest_path: Path,
    *,
    include_files: bool = False,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = load_package_file(manifest_path)
    files: list[dict[str, Any]] = []
    missing_sources: list[str] = []
    file_count = 0
    available = True
    availability_error: str | None = None
    try:
        missing_sources = collect_missing_sources(data, manifest_path, artifact_roots=artifact_roots)
        available = len(missing_sources) == 0
        if include_files:
            files = expanded_package_entries(data, manifest_path, artifact_roots=artifact_roots)
            file_count = len(files)
        else:
            file_count = count_package_entries(data, manifest_path, artifact_roots=artifact_roots)
    except ValueError as exc:
        available = False
        availability_error = str(exc)
    return {
        "package_id": data["package_id"],
        "version": data["version"],
        "profile_id": data["profile_id"],
        "install_root": data["install_root"],
        "file_count": file_count,
        "manifest": str(manifest_path),
        "description": data.get("metadata", {}).get("description", ""),
        "metadata": data.get("metadata", {}),
        "depends": data.get("depends", []),
        "plugins": data.get("plugins", []),
        "plugin_data": data.get("plugin_data", []),
        "files": files,
        "available": available,
        "missing_sources": missing_sources,
        "missing_count": len(missing_sources),
        "availability_error": availability_error,
    }


def verify_package_sources(
    manifest_path: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = load_package_file(manifest_path)
    declared_paths = collect_declared_source_paths(data, manifest_path, artifact_roots=artifact_roots)
    missing_sources = [path for path in declared_paths if not Path(path).exists()]
    expanded_files = expanded_package_entries(data, manifest_path, artifact_roots=artifact_roots)
    missing_files = [item["source"] for item in expanded_files if not Path(item["source"]).exists()]
    return {
        "package_id": data["package_id"],
        "version": data["version"],
        "manifest": str(manifest_path),
        "declared_source_count": len(declared_paths),
        "expanded_file_count": len(expanded_files),
        "missing_sources": missing_sources,
        "missing_files": missing_files,
        "ok": not missing_sources and not missing_files,
    }


def find_package_manifest(repo_root: Path, package_id: str, version: str | None = None) -> Path | None:
    matches = [
        manifest_path
        for manifest_path in repo_package_manifests(repo_root)
        if load_package_file(manifest_path)["package_id"] == package_id
    ]
    if not matches:
        return None
    if version is not None:
        for manifest_path in matches:
            data = load_package_file(manifest_path)
            if data["version"] == version:
                return manifest_path
        return None
    return sorted(matches, key=lambda path: load_package_file(path)["version"])[-1]


def list_available_packages(repo_root: Path, artifact_roots: dict[str, str] | None = None) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for manifest_path in repo_package_manifests(repo_root):
        summary = package_summary_from_manifest(manifest_path, artifact_roots=artifact_roots)
        packages.append(
            {
                "package_id": summary["package_id"],
                "version": summary["version"],
                "profile_id": summary["profile_id"],
                "install_root": summary["install_root"],
                "file_count": summary["file_count"],
                "manifest": summary["manifest"],
                "description": summary["description"],
                "available": summary["available"],
                "missing_count": summary["missing_count"],
            }
        )
    return sorted(packages, key=lambda item: (item["package_id"], item["version"]))


def managed_state_root(managed_root: Path) -> Path:
    return managed_installed_state_root(managed_root)


def installed_states(state_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for state_path in sorted(state_root.glob("*.json")):
        data = load_json(state_path)
        package = data.get("package", {})
        bundle = data.get("bundle", {})
        results.append(
            {
                "state_path": str(state_path),
                "package_id": package.get("package_id", ""),
                "package_version": package.get("package_version", ""),
                "profile_id": package.get("profile_id", bundle.get("profile_id", "")),
                "install_root": package.get("install_root", ""),
                "bundle_id": bundle.get("bundle_id", ""),
                "bundle_type": bundle.get("bundle_type", ""),
                "updated_at": data.get("updated_at", ""),
                "tracked_file_count": len(package.get("tracked_files", [])),
                "raw": data,
            }
        )
    return results


def find_installed_state(state_root: Path, package_id: str) -> dict[str, Any] | None:
    matches = [item for item in installed_states(state_root) if item["package_id"] == package_id]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item["updated_at"])[-1]
