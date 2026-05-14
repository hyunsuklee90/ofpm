from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ofpm.apt import (
    apt_artifact_root,
    apt_dependency_names,
    apt_download_package,
    apt_package_manifest_path,
    apt_policy_version,
    apt_show_metadata,
    detect_apt_context,
    find_apt_package_manifest,
    list_apt_packages,
)
from ofpm.state_db import (
    managed_installed_state_root,
    managed_receipt_file,
    managed_state_file as db_managed_state_file,
    record_install,
    record_removal,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def progress(message: str) -> None:
    print(message, flush=True)


def user_config_root() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return Path(xdg).expanduser() / "ofpm"
    return Path.home() / ".config" / "ofpm"


def repo_local_config_root(repo_root: Path) -> Path:
    return repo_root / "local"


def user_repos_config_path() -> Path:
    return user_config_root() / "repos.json"


def repo_repos_config_path(repo_root: Path) -> Path:
    return repo_local_config_root(repo_root) / "repos.json"


def legacy_artifact_roots_path(repo_root: Path) -> Path:
    return repo_local_config_root(repo_root) / "artifact-roots.json"


def load_artifact_roots(repo_root: Path) -> dict[str, str]:
    artifact_roots: dict[str, str] = {}
    for config_path in [legacy_artifact_roots_path(repo_root)]:
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


def repo_package_manifests(catalog_root: Path) -> list[Path]:
    return sorted(catalog_root.glob("packages/*/*/package.json"))


def list_available_packages(catalog_root: Path, artifact_roots: dict[str, str] | None = None) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for manifest_path in repo_package_manifests(catalog_root):
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


def registered_repos(repo_root: Path) -> dict[str, str]:
    repos: dict[str, str] = {}
    repo_config = repo_repos_config_path(repo_root)
    user_config = user_repos_config_path()
    if repo_config.exists():
        repos.update(load_json(repo_config))
    if user_config.exists():
        repos.update(load_json(user_config))
    return dict(sorted(repos.items()))


def resolve_artifact_root(package_data: dict[str, Any], artifact_roots: dict[str, str] | None) -> Path | None:
    root_id = package_data.get("metadata", {}).get("artifact_root_id")
    if not root_id:
        return None
    roots = artifact_roots or {}
    configured = roots.get(root_id)
    if not configured:
        return None
    return Path(configured).expanduser().resolve()


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


def package_summary_from_manifest(
    manifest_path: Path,
    *,
    include_files: bool = False,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = load_json(manifest_path)
    files: list[dict[str, Any]] = []
    missing_sources: list[str] = []
    file_count = 0
    available = True
    availability_error: str | None = None
    try:
        missing_sources = collect_missing_sources(
            data,
            manifest_path,
            artifact_roots=artifact_roots,
        )
        available = len(missing_sources) == 0
        if include_files:
            files = expanded_package_entries(data, manifest_path, artifact_roots=artifact_roots)
            file_count = len(files)
        else:
            file_count = count_package_entries(
                data,
                manifest_path,
                artifact_roots=artifact_roots,
            )
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
    data = load_json(manifest_path)
    declared_paths = collect_declared_source_paths(
        data,
        manifest_path,
        artifact_roots=artifact_roots,
    )
    missing_sources = [path for path in declared_paths if not Path(path).exists()]
    expanded_files = expanded_package_entries(
        data,
        manifest_path,
        artifact_roots=artifact_roots,
    )
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


def find_package_manifest(catalog_root: Path, package_id: str, version: str | None = None) -> Path | None:
    matches = [
        manifest_path
        for manifest_path in repo_package_manifests(catalog_root)
        if load_json(manifest_path)["package_id"] == package_id
    ]
    if not matches:
        return None
    if version is not None:
        for manifest_path in matches:
            data = load_json(manifest_path)
            if data["version"] == version:
                return manifest_path
        return None
    return sorted(matches, key=lambda path: load_json(path)["version"])[-1]


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


def inferred_receipt_metadata(installed_state: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    package = installed_state["raw"]["package"]
    managed_objects: dict[str, Any] = {
        "version_root": package.get("version_root", ""),
        "current_path": package.get("current_path", ""),
        "executables": package.get("executables", []),
    }
    if "prefix_root" in package:
        managed_objects["prefix_root"] = package["prefix_root"]
    if "config_dir" in package:
        managed_objects["config_dir"] = package["config_dir"]
    if "library_dir" in package:
        managed_objects["library_dir"] = package["library_dir"]
    if "models_path" in package:
        managed_objects["models_path"] = package["models_path"]

    artifact_ref: dict[str, Any] = {}
    if "artifacts" in package:
        artifact_ref = {"type": "stored-artifact", "paths": package["artifacts"]}
    elif "source_artifacts" in package:
        artifact_ref = {"type": "source-artifacts", "paths": package["source_artifacts"]}

    package_id = installed_state["package_id"]
    if package_id == "node-runtime":
        return "ofpm-native", "archive-extract", managed_objects, artifact_ref
    if package_id == "ollama-runtime":
        return "ofpm-native", "managed-runtime", managed_objects, artifact_ref
    if package_id == "pi-agent":
        return "ofpm-native", "offline-npm-prefix", managed_objects, artifact_ref
    if package_id.startswith("ollama-model-"):
        return "ofpm-native", "managed-model-store", managed_objects, artifact_ref
    return "ofpm-native", "legacy-state-import", managed_objects, artifact_ref


def sync_managed_state_db(managed_root: Path) -> dict[str, int]:
    installed = installed_states(managed_state_root(managed_root))
    created = 0
    failed = 0
    for item in installed:
        receipt_path = managed_receipt_file(managed_root, item["package_id"])
        if receipt_path.exists():
            continue
        provider, strategy, managed_objects, artifact_ref = inferred_receipt_metadata(item)
        try:
            record_install(
                managed_root,
                item["raw"],
                provider=provider,
                strategy=strategy,
                managed_objects=managed_objects,
                artifact_ref=artifact_ref,
                write_history=False,
                write_state=False,
            )
            created += 1
        except OSError:
            failed += 1
    return {"installed_count": len(installed), "created_receipts": created, "failed_receipts": failed}


def managed_state_root(managed_root: Path) -> Path:
    return managed_installed_state_root(managed_root)


def managed_state_file(managed_root: Path, package_id: str) -> Path:
    return db_managed_state_file(managed_root, package_id)


def resolve_package_specs(
    catalog_root: Path,
    package_specs: list[str],
    *,
    artifact_roots: dict[str, str] | None = None,
) -> list[tuple[str, Path, dict[str, Any]]]:
    resolved: list[tuple[str, Path, dict[str, Any]]] = []
    seen_specs: set[str] = set()
    for spec in package_specs:
        if spec in seen_specs:
            continue
        seen_specs.add(spec)
        if "@" in spec:
            package_id, version = spec.split("@", 1)
        else:
            package_id, version = spec, None
        manifest_path = find_package_manifest(catalog_root, package_id, version)
        if manifest_path is None:
            raise ValueError(f"package not found: {spec}")
        summary = package_summary_from_manifest(
            manifest_path,
            include_files=True,
            artifact_roots=artifact_roots,
        )
        resolved.append((spec, manifest_path, summary))
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_store_blob(store_root: Path, source: Path) -> dict[str, Any]:
    sha256 = sha256_file(source)
    dest = blob_store_path(store_root, sha256)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(source, dest)
    return {
        "sha256": sha256,
        "size": source.stat().st_size,
        "store_path": str(dest),
    }


def blob_store_path(store_root: Path, sha256: str) -> Path:
    return store_root / "blobs" / "sha256" / sha256[:2] / sha256[2:4] / sha256


def package_root_from_manifest(package_manifest: Path) -> Path:
    return package_manifest.parent


def normalize_mode(mode: str | None, source: Path) -> str:
    if mode:
        return mode
    return format(source.stat().st_mode & 0o777, "04o")


def relative_target_path(install_root: str, target: str) -> str:
    clean_install_root = install_root.strip("/").replace("\\", "/")
    clean_target = target.strip("/").replace("\\", "/")
    return "/".join(part for part in [clean_install_root, clean_target] if part)


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


def build_file_index(
    package_data: dict[str, Any],
    package_manifest: Path,
    store_root: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for item in expanded_package_entries(package_data, package_manifest, artifact_roots=artifact_roots):
        source = Path(item["source"]).resolve()
        staged = ensure_store_blob(store_root, source)
        files.append(
            {
                "target": item["target"],
                "install_path": relative_target_path(package_data["install_root"], item["target"]),
                "source": str(source),
                "sha256": staged["sha256"],
                "size": staged["size"],
                "mode": normalize_mode(item.get("mode"), source),
            }
        )
    return sorted(files, key=lambda entry: entry["install_path"])


def export_bundle_name(name: str, bundle_format: str) -> str:
    if bundle_format == "dir":
        return name
    if bundle_format == "tar.gz":
        return f"{name}.tar.gz"
    raise ValueError(f"unsupported export format: {bundle_format}")


def build_export_manifest(
    bundle_name: str,
    package_entries: list[tuple[str, Path, dict[str, Any]]],
) -> dict[str, Any]:
    package_items: list[dict[str, Any]] = []
    file_items: list[dict[str, Any]] = []
    profiles: dict[str, list[str]] = defaultdict(list)

    for _, manifest_path, summary in package_entries:
        package_items.append(
            {
                "package_id": summary["package_id"],
                "version": summary["version"],
                "profile_id": summary["profile_id"],
                "install_root": summary["install_root"],
                "manifest": str(manifest_path),
                "description": summary["description"],
                "file_count": summary["file_count"],
            }
        )
        profiles[summary["profile_id"]].append(f"{summary['package_id']}@{summary['version']}")
        for file_item in summary["files"]:
            install_path = relative_target_path(summary["install_root"], file_item["target"])
            relpath = f"files/{install_path}"
            source = Path(file_item["source"]).resolve()
            file_items.append(
                {
                    "package_id": summary["package_id"],
                    "package_version": summary["version"],
                    "bundle_relpath": relpath,
                    "install_path": install_path,
                    "source": str(source),
                    "sha256": sha256_file(source),
                    "size": source.stat().st_size,
                    "mode": normalize_mode(file_item.get("mode"), source),
                }
            )

    return {
        "schema_version": "1",
        "bundle_name": bundle_name,
        "bundle_type": "export",
        "created_at": utc_now(),
        "packages": package_items,
        "profiles": dict(profiles),
        "files": sorted(file_items, key=lambda item: (item["package_id"], item["bundle_relpath"])),
    }


def materialize_export_bundle_dir(
    out_dir: Path,
    bundle_manifest: dict[str, Any],
) -> Path:
    bundle_root = out_dir / bundle_manifest["bundle_name"]
    if bundle_root.exists():
        raise FileExistsError(f"bundle output already exists: {bundle_root}")
    bundle_root.mkdir(parents=True, exist_ok=False)
    for file_item in bundle_manifest["files"]:
        destination = bundle_root / file_item["bundle_relpath"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_item["source"], destination)
        os.chmod(destination, int(file_item["mode"], 8))
    manifest_path = bundle_root / "bundle.json"
    dump_json(manifest_path, bundle_manifest)
    return bundle_root


def archive_export_bundle_dir(bundle_root: Path) -> Path:
    archive_path = bundle_root.with_suffix(".tar.gz")
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(bundle_root, arcname=bundle_root.name)
    return archive_path


def detect_single_subdir(path: Path, *, exclude_names: set[str] | None = None) -> Path:
    excluded = exclude_names or set()
    subdirs = [entry for entry in path.iterdir() if entry.is_dir() and entry.name not in excluded]
    if len(subdirs) != 1:
        raise ValueError(f"expected exactly one extracted subdir under {path}")
    return subdirs[0]


def reset_current_link(current_link: Path, target: Path) -> None:
    current_link.parent.mkdir(parents=True, exist_ok=True)
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()
    current_link.symlink_to(target, target_is_directory=target.is_dir())


def package_files_by_target(
    package_data: dict[str, Any],
    package_manifest: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for entry in expanded_package_entries(package_data, package_manifest, artifact_roots=artifact_roots):
        files[entry["target"]] = Path(entry["source"]).resolve()
    return files


def required_dependency_errors(managed_root: Path, package_data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for dep in package_data.get("depends", []):
        if not dep.get("required", False):
            continue
        installed = find_installed_state(managed_state_root(managed_root), dep["package_id"])
        if installed is None:
            errors.append(f"missing required dependency: {dep['package_id']} {dep.get('version', '')}".rstrip())
            continue
        required_version = dep.get("version")
        if required_version and installed["package_version"] != required_version:
            errors.append(
                f"dependency version mismatch: {dep['package_id']} "
                f"(installed={installed['package_version']} required={required_version})"
            )
    return errors


def default_pi_models_config() -> dict[str, Any]:
    return {"providers": {}}


def repo_root_from_runtime_state() -> Path:
    return Path(__file__).resolve().parents[2]


def ollama_provider_from_installed_models(managed_root: Path) -> dict[str, Any] | None:
    installed = installed_states(managed_state_root(managed_root))
    runtime = next((item for item in installed if item["package_id"] == "ollama-runtime"), None)
    if runtime is None:
        return None

    models: list[dict[str, Any]] = []
    catalog_root = repo_root_from_runtime_state() / "catalog"
    for item in installed:
        if not item["package_id"].startswith("ollama-model-"):
            continue
        manifest_path = find_package_manifest(catalog_root, item["package_id"], item["package_version"])
        if manifest_path is None:
            continue
        manifest = load_json(manifest_path)
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


def reconcile_managed_integrations(managed_root: Path) -> dict[str, Any]:
    installed = installed_states(managed_state_root(managed_root))
    pi_state = next((item for item in installed if item["package_id"] == "pi-agent"), None)
    result: dict[str, Any] = {"updated": [], "notes": []}
    if pi_state is None:
        result["notes"].append("pi-agent not installed; no pi integration updates needed")
        return result

    config_dir = Path(pi_state["raw"]["package"]["config_dir"])
    config_path = config_dir / "models.json"
    config = default_pi_models_config()
    ollama_provider = ollama_provider_from_installed_models(managed_root)
    if ollama_provider is not None:
        config["providers"]["ollama"] = ollama_provider
    dump_json(config_path, config)
    result["updated"].append(str(config_path))
    result["notes"].append("regenerated pi models.json from installed ofpm package state")
    return result


def managed_ollama_models_root(managed_root: Path) -> Path:
    return managed_root / "data" / "ollama-models"


def refresh_managed_ollama_models_store(managed_root: Path) -> dict[str, Any]:
    store_root = managed_ollama_models_root(managed_root)
    if store_root.exists():
        shutil.rmtree(store_root)
    store_root.mkdir(parents=True, exist_ok=True)

    installed = installed_states(managed_state_root(managed_root))
    model_states = [item for item in installed if item["package_id"].startswith("ollama-model-")]
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
                src_sha = sha256_file(path)
                dst_sha = sha256_file(destination)
                if src_sha != dst_sha:
                    raise ValueError(f"shared ollama model store conflict for {destination}")
                continue
            shutil.copy2(path, destination)
            copied_files += 1
    return {
        "store_root": str(store_root),
        "package_count": len(model_states),
        "copied_files": copied_files,
    }


def install_node_runtime(
    managed_root: Path,
    package_manifest: Path,
    package_data: dict[str, Any],
    *,
    root_kind: str,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    package_id = package_data["package_id"]
    version = package_data["version"]
    version_root = managed_root / "payloads" / package_id / version
    artifacts_root = version_root / "artifacts"

    progress(f"[ofpm] install {package_id}@{version}: preparing managed root")
    progress(f"  manifest: {package_manifest}")
    progress(f"  managed root: {managed_root}")
    progress(f"  version root: {version_root}")
    progress(f"  root kind: {root_kind}")

    if version_root.exists():
        raise FileExistsError(f"package version already installed at {version_root}")

    managed_root.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=False)

    entries = expanded_package_entries(package_data, package_manifest, artifact_roots=artifact_roots)
    if len(entries) != 1:
        raise ValueError("node-runtime install expects exactly one source artifact")

    tarball_source = Path(entries[0]["source"]).resolve()
    tarball_dest = artifacts_root / tarball_source.name
    progress(f"[ofpm] install {package_id}@{version}: copying source artifact")
    progress(f"  source: {tarball_source}")
    progress(f"  destination: {tarball_dest}")
    shutil.copy2(tarball_source, tarball_dest)

    progress(f"[ofpm] install {package_id}@{version}: extracting runtime archive")
    progress(f"  archive: {tarball_dest}")
    progress(f"  extract destination: {version_root}")
    with tarfile.open(tarball_dest, "r:xz") as tar:
        tar.extractall(version_root)

    extracted_root = detect_single_subdir(version_root, exclude_names={"artifacts"})
    current_link = managed_root / "payloads" / package_id / "current"
    reset_current_link(current_link, extracted_root)
    progress(f"[ofpm] install {package_id}@{version}: activating current link")
    progress(f"  extracted root: {extracted_root}")
    progress(f"  current link: {current_link} -> {extracted_root}")

    state = {
        "schema_version": "1",
        "updated_at": utc_now(),
        "install_type": "managed-install",
        "root_kind": root_kind,
        "managed_root": str(managed_root),
        "package": {
            "package_id": package_id,
            "package_version": version,
            "profile_id": package_data["profile_id"],
            "install_root": package_data["install_root"],
            "description": package_data.get("metadata", {}).get("description", ""),
            "env": package_data.get("env", {}),
            "version_root": str(version_root),
            "current_path": str(current_link),
            "executables": [
                str(current_link / "bin" / "node"),
                str(current_link / "bin" / "npm"),
                str(current_link / "bin" / "npx"),
            ],
            "artifacts": [
                {
                    "source": str(tarball_source),
                    "stored_path": str(tarball_dest),
                    "sha256": sha256_file(tarball_dest),
                    "size": tarball_dest.stat().st_size,
                }
            ],
        },
    }
    state_file = managed_state_file(managed_root, package_id)
    record_install(
        managed_root,
        state,
        provider="ofpm-native",
        strategy="archive-extract",
        managed_objects={
            "version_root": str(version_root),
            "current_path": str(current_link),
            "executables": state["package"]["executables"],
            "artifacts_root": str(artifacts_root),
        },
        artifact_ref={"type": "stored-artifact", "paths": state["package"]["artifacts"]},
    )
    progress(f"[ofpm] install {package_id}@{version}: recorded installed state")
    progress(f"  state file: {state_file}")
    return state


def install_managed_files_package(
    managed_root: Path,
    package_manifest: Path,
    package_data: dict[str, Any],
    *,
    root_kind: str,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    package_id = package_data["package_id"]
    version = package_data["version"]
    version_root = managed_root / "payloads" / package_id / version
    current_link = managed_root / "payloads" / package_id / "current"

    progress(f"[ofpm] install {package_id}@{version}: preparing managed root")
    progress(f"  manifest: {package_manifest}")
    progress(f"  managed root: {managed_root}")
    progress(f"  version root: {version_root}")
    progress(f"  root kind: {root_kind}")
    progress("  package intent: generic managed file payload")

    dependency_errors = required_dependency_errors(managed_root, package_data)
    if dependency_errors:
        raise ValueError("; ".join(dependency_errors))

    if version_root.exists():
        raise FileExistsError(f"package version already installed at {version_root}")

    entries = expanded_package_entries(package_data, package_manifest, artifact_roots=artifact_roots)
    source_artifacts = sorted(
        {
            str(Path(item["source"]).resolve())
            for item in entries
        }
    )
    executables: list[str] = []
    tracked_files: list[dict[str, Any]] = []

    managed_root.mkdir(parents=True, exist_ok=True)
    version_root.mkdir(parents=True, exist_ok=False)
    for item in entries:
        source = Path(item["source"]).resolve()
        target_relpath = item["target"].replace("\\", "/")
        destination = version_root / target_relpath
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        mode = normalize_mode(item.get("mode"), source)
        os.chmod(destination, int(mode, 8))
        tracked_files.append(
            {
                "install_path": relative_target_path(package_data["install_root"], target_relpath),
                "sha256": sha256_file(destination),
                "size": destination.stat().st_size,
                "mode": mode,
            }
        )
        if target_relpath.startswith("bin/"):
            executables.append(str(current_link / target_relpath))

    reset_current_link(current_link, version_root)
    progress(f"[ofpm] install {package_id}@{version}: activated current link")
    progress(f"  current link: {current_link} -> {version_root}")

    state = {
        "schema_version": "1",
        "updated_at": utc_now(),
        "install_type": "managed-install",
        "root_kind": root_kind,
        "managed_root": str(managed_root),
        "package": {
            "package_id": package_id,
            "package_version": version,
            "profile_id": package_data["profile_id"],
            "install_root": package_data["install_root"],
            "description": package_data.get("metadata", {}).get("description", ""),
            "env": package_data.get("env", {}),
            "version_root": str(version_root),
            "current_path": str(current_link),
            "executables": executables,
            "tracked_files": tracked_files,
            "source_artifacts": source_artifacts,
        },
    }
    state_file = managed_state_file(managed_root, package_id)
    record_install(
        managed_root,
        state,
        provider="ofpm-native",
        strategy="managed-files",
        managed_objects={
            "version_root": str(version_root),
            "current_path": str(current_link),
            "executables": executables,
        },
        artifact_ref={"type": "source-artifacts", "paths": source_artifacts},
    )
    progress(f"[ofpm] install {package_id}@{version}: recorded installed state")
    progress(f"  state file: {state_file}")
    return state


def install_ollama_runtime(
    managed_root: Path,
    package_manifest: Path,
    package_data: dict[str, Any],
    *,
    root_kind: str,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    package_id = package_data["package_id"]
    version = package_data["version"]
    version_root = managed_root / "payloads" / package_id / version
    progress(f"[ofpm] install {package_id}@{version}: preparing managed root")
    progress(f"  manifest: {package_manifest}")
    progress(f"  managed root: {managed_root}")
    progress(f"  version root: {version_root}")
    progress(f"  root kind: {root_kind}")
    if version_root.exists():
        raise FileExistsError(f"package version already installed at {version_root}")

    managed_root.mkdir(parents=True, exist_ok=True)
    version_root.mkdir(parents=True, exist_ok=False)

    files = package_files_by_target(package_data, package_manifest, artifact_roots=artifact_roots)
    archive_source = files.get("archives/ollama-linux-amd64.tar.zst")
    binary_source = files.get("bin/ollama")

    install_mode = "archive"
    if archive_source and archive_source.exists():
        progress(f"[ofpm] install {package_id}@{version}: extracting full distribution archive")
        progress(f"  archive source: {archive_source}")
        progress(f"  extract destination: {version_root}")
        subprocess.run(
            ["tar", "--zstd", "-xf", str(archive_source), "-C", str(version_root)],
            check=True,
        )
    elif binary_source and binary_source.exists():
        install_mode = "binary-only"
        progress(f"[ofpm] install {package_id}@{version}: archive missing, installing raw binary only")
        progress(f"  binary source: {binary_source}")
        progress(f"  binary destination: {version_root / 'bin' / 'ollama'}")
        (version_root / "bin").mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary_source, version_root / "bin" / "ollama")
        os.chmod(version_root / "bin" / "ollama", 0o755)
    else:
        raise FileNotFoundError("missing ollama runtime archive and raw binary")

    current_link = managed_root / "payloads" / package_id / "current"
    reset_current_link(current_link, version_root)
    progress(f"[ofpm] install {package_id}@{version}: activating current link")
    progress(f"  current link: {current_link} -> {version_root}")
    progress(f"  ollama executable: {current_link / 'bin' / 'ollama'}")
    library_dir = current_link / "lib" / "ollama"
    progress(f"  library dir: {library_dir}")
    progress("  note: archive mode preserves bundled CPU/CUDA/Vulkan runner libraries")
    state = {
        "schema_version": "1",
        "updated_at": utc_now(),
        "install_type": "managed-install",
        "root_kind": root_kind,
        "managed_root": str(managed_root),
        "package": {
            "package_id": package_id,
            "package_version": version,
            "profile_id": package_data["profile_id"],
            "install_root": package_data["install_root"],
            "description": package_data.get("metadata", {}).get("description", ""),
            "env": package_data.get("env", {}),
            "version_root": str(version_root),
            "current_path": str(current_link),
            "executables": [str(current_link / "bin" / "ollama")],
            "library_dir": str(library_dir),
            "install_mode": install_mode,
            "source_artifacts": [
                str(path) for path in [archive_source, binary_source] if path is not None and path.exists()
            ],
        },
    }
    state_file = managed_state_file(managed_root, package_id)
    record_install(
        managed_root,
        state,
        provider="ofpm-native",
        strategy="managed-runtime",
        managed_objects={
            "version_root": str(version_root),
            "current_path": str(current_link),
            "executables": state["package"]["executables"],
            "library_dir": str(library_dir),
        },
        artifact_ref={"type": "source-artifacts", "paths": state["package"]["source_artifacts"]},
    )
    model_store_result = refresh_managed_ollama_models_store(managed_root)
    reconcile_result = reconcile_managed_integrations(managed_root)
    progress(f"[ofpm] install {package_id}@{version}: recorded installed state")
    progress(f"  state file: {state_file}")
    progress(f"  refreshed shared ollama model store: {model_store_result['store_root']}")
    progress(f"  shared store package count: {model_store_result['package_count']}")
    progress(f"  shared store copied files: {model_store_result['copied_files']}")
    for path in reconcile_result["updated"]:
        progress(f"  reconciled integration file: {path}")
    for note in reconcile_result["notes"]:
        progress(f"  integration note: {note}")
    return state


def install_pi_agent(
    managed_root: Path,
    package_manifest: Path,
    package_data: dict[str, Any],
    *,
    root_kind: str,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    package_id = package_data["package_id"]
    version = package_data["version"]
    version_root = managed_root / "payloads" / package_id / version
    progress(f"[ofpm] install {package_id}@{version}: preparing managed root")
    progress(f"  manifest: {package_manifest}")
    progress(f"  managed root: {managed_root}")
    progress(f"  version root: {version_root}")
    progress(f"  root kind: {root_kind}")
    progress(f"  package intent: offline npm install + managed config + rg/fd helpers")

    dependency_errors = required_dependency_errors(managed_root, package_data)
    if dependency_errors:
        raise ValueError("; ".join(dependency_errors))

    node_state = find_installed_state(managed_state_root(managed_root), "node-runtime")
    if node_state is None:
        raise ValueError("node-runtime must be installed before pi-agent")

    node_current = Path(node_state["raw"]["package"]["current_path"])
    npm_path = node_current / "bin" / "npm"
    if not npm_path.exists():
        raise FileNotFoundError(f"missing npm executable: {npm_path}")

    progress(f"[ofpm] install {package_id}@{version}: checking required dependencies")
    progress(f"  required dependency satisfied: node-runtime via {node_current}")
    if version_root.exists():
        raise FileExistsError(f"package version already installed at {version_root}")

    files = package_files_by_target(package_data, package_manifest, artifact_roots=artifact_roots)
    tgz_source = files.get("archives/earendil-works-pi-coding-agent-0.74.0.tgz")
    rg_source = files.get("bin/rg")
    fd_source = files.get("bin/fd")
    cache_item = next(item for item in package_data["files"] if "source_dir_relpath" in item or "source_dir" in item)
    npm_cache_source = resolve_source_path(
        package_data,
        package_manifest,
        cache_item,
        key="source_dir",
        artifact_roots=artifact_roots,
    )

    if tgz_source is None:
        raise FileNotFoundError("pi-agent requires tgz source")
    progress(f"  package tgz: {tgz_source}")
    progress(f"  npm cache source: {npm_cache_source}")
    if rg_source:
        progress(f"  rg helper source: {rg_source}")
    if fd_source:
        progress(f"  fd helper source: {fd_source}")

    managed_root.mkdir(parents=True, exist_ok=True)
    version_root.mkdir(parents=True, exist_ok=False)
    prefix_root = version_root / "prefix"
    config_dir = version_root / "config" / "agent"
    bin_dir = version_root / "bin"
    prefix_root.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    progress(f"  npm global prefix: {prefix_root}")
    progress(f"  managed config dir: {config_dir}")
    progress(f"  managed helper bin dir: {bin_dir}")
    progress("  models.json policy: regenerate from installed ofpm package state")

    with tempfile.TemporaryDirectory(prefix="ofpm-npm-cache-") as temp_cache:
        temp_cache_root = Path(temp_cache)
        progress(f"[ofpm] install {package_id}@{version}: copying offline npm cache to writable temp dir")
        progress(f"  temp cache dir: {temp_cache_root}")
        shutil.copytree(npm_cache_source, temp_cache_root, dirs_exist_ok=True)
        env = os.environ.copy()
        env["PATH"] = f"{node_current / 'bin'}:{env.get('PATH', '')}"
        env["PI_CODING_AGENT_DIR"] = str(config_dir)
        progress(f"[ofpm] install {package_id}@{version}: running offline npm install")
        progress(f"  npm executable: {npm_path}")
        progress(f"  command: npm install -g --offline --cache {temp_cache_root} --prefix {prefix_root} {tgz_source}")
        progress(f"  env PI_CODING_AGENT_DIR: {config_dir}")
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
    progress(f"  installed pi executable: {installed_pi}")

    current_link = version_root.parent / "current"
    reset_current_link(current_link, version_root)
    reset_current_link(bin_dir / "pi", installed_pi)
    progress(f"[ofpm] install {package_id}@{version}: staging helper binaries and config")
    progress(f"  current link: {current_link} -> {version_root}")
    progress(f"  managed pi launcher link: {bin_dir / 'pi'} -> {installed_pi}")
    if rg_source and rg_source.exists():
        shutil.copy2(rg_source, bin_dir / "rg")
        os.chmod(bin_dir / "rg", 0o755)
        progress(f"  installed rg helper: {bin_dir / 'rg'}")
    if fd_source and fd_source.exists():
        shutil.copy2(fd_source, bin_dir / "fd")
        os.chmod(bin_dir / "fd", 0o755)
        progress(f"  installed fd helper: {bin_dir / 'fd'}")
    dump_json(config_dir / "models.json", default_pi_models_config())
    progress(f"  wrote initial models.json template: {config_dir / 'models.json'}")

    state = {
        "schema_version": "1",
        "updated_at": utc_now(),
        "install_type": "managed-install",
        "root_kind": root_kind,
        "managed_root": str(managed_root),
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
            "executables": [
                str(current_link / "bin" / "pi"),
                str(current_link / "bin" / "rg"),
                str(current_link / "bin" / "fd"),
            ],
            "node_runtime_path": str(node_current),
            "source_artifacts": [str(tgz_source), str(npm_cache_source)],
        },
    }
    state_file = managed_state_file(managed_root, package_id)
    record_install(
        managed_root,
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
    reconcile_result = reconcile_managed_integrations(managed_root)
    progress(f"[ofpm] install {package_id}@{version}: recorded installed state")
    progress(f"  state file: {state_file}")
    for path in reconcile_result["updated"]:
        progress(f"  reconciled integration file: {path}")
    for note in reconcile_result["notes"]:
        progress(f"  integration note: {note}")
    return state


def install_ollama_model_bundle(
    managed_root: Path,
    package_manifest: Path,
    package_data: dict[str, Any],
    *,
    root_kind: str,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    package_id = package_data["package_id"]
    version = package_data["version"]
    version_root = managed_root / "payloads" / package_id / version
    progress(f"[ofpm] install {package_id}@{version}: preparing managed root")
    progress(f"  manifest: {package_manifest}")
    progress(f"  managed root: {managed_root}")
    progress(f"  version root: {version_root}")
    progress(f"  root kind: {root_kind}")
    progress("  package intent: stage an Ollama model store that can later be activated via OLLAMA_MODELS")

    if version_root.exists():
        raise FileExistsError(f"package version already installed at {version_root}")

    files = package_files_by_target(package_data, package_manifest, artifact_roots=artifact_roots)
    source_root = resolve_source_path(
        package_data,
        package_manifest,
        next(item for item in package_data["files"] if "source_dir_relpath" in item or "source_dir" in item),
        key="source_dir",
        artifact_roots=artifact_roots,
    )
    source_dir_name = source_root.name
    target_dir = version_root / source_dir_name

    managed_root.mkdir(parents=True, exist_ok=True)
    version_root.mkdir(parents=True, exist_ok=False)
    progress(f"[ofpm] install {package_id}@{version}: copying model store")
    progress(f"  source dir: {source_root}")
    progress(f"  destination dir: {target_dir}")
    shutil.copytree(source_root, target_dir, dirs_exist_ok=False)

    current_link = managed_root / "payloads" / package_id / "current"
    reset_current_link(current_link, version_root)
    progress(f"[ofpm] install {package_id}@{version}: activating current link")
    progress(f"  current link: {current_link} -> {version_root}")
    progress(f"  managed OLLAMA_MODELS candidate: {current_link / source_dir_name}")

    state = {
        "schema_version": "1",
        "updated_at": utc_now(),
        "install_type": "managed-install",
        "root_kind": root_kind,
        "managed_root": str(managed_root),
        "package": {
            "package_id": package_id,
            "package_version": version,
            "profile_id": package_data["profile_id"],
            "install_root": package_data["install_root"],
            "description": package_data.get("metadata", {}).get("description", ""),
            "env": package_data.get("env", {}),
            "version_root": str(version_root),
            "current_path": str(current_link),
            "models_path": str(current_link / source_dir_name),
            "source_artifacts": [str(source_root)],
            "file_count": len(files),
        },
    }
    state_file = managed_state_file(managed_root, package_id)
    record_install(
        managed_root,
        state,
        provider="ofpm-native",
        strategy="managed-model-store",
        managed_objects={
            "version_root": str(version_root),
            "current_path": str(current_link),
            "models_path": str(current_link / source_dir_name),
        },
        artifact_ref={"type": "source-artifacts", "paths": state["package"]["source_artifacts"]},
    )
    reconcile_result = reconcile_managed_integrations(managed_root)
    progress(f"[ofpm] install {package_id}@{version}: recorded installed state")
    progress(f"  state file: {state_file}")
    for path in reconcile_result["updated"]:
        progress(f"  reconciled integration file: {path}")
    for note in reconcile_result["notes"]:
        progress(f"  integration note: {note}")
    return state


def remove_node_runtime(managed_root: Path, installed_state: dict[str, Any]) -> dict[str, Any]:
    package = installed_state["raw"]["package"]
    version_root = Path(package["version_root"])
    current_path = Path(package["current_path"])

    if current_path.is_symlink():
        try:
            resolved_target = current_path.resolve()
            if resolved_target == version_root.resolve() or version_root.resolve() in resolved_target.parents:
                current_path.unlink()
        except FileNotFoundError:
            current_path.unlink()

    if version_root.exists():
        shutil.rmtree(version_root)

    record_removal(managed_root, installed_state)

    refresh_managed_ollama_models_store(managed_root)
    reconcile_managed_integrations(managed_root)

    return {
        "package_id": package["package_id"],
        "package_version": package["package_version"],
        "managed_root": str(managed_root),
        "removed_version_root": str(version_root),
    }


def remove_managed_payload(managed_root: Path, installed_state: dict[str, Any]) -> dict[str, Any]:
    package = installed_state["raw"]["package"]
    version_root = Path(package["version_root"])
    current_path = Path(package["current_path"])

    if current_path.is_symlink():
        try:
            resolved_target = current_path.resolve()
            if resolved_target == version_root.resolve() or version_root.resolve() in resolved_target.parents:
                current_path.unlink()
        except FileNotFoundError:
            current_path.unlink()

    if version_root.exists():
        shutil.rmtree(version_root)

    record_removal(managed_root, installed_state)

    reconcile_managed_integrations(managed_root)

    return {
        "package_id": package["package_id"],
        "package_version": package["package_version"],
        "managed_root": str(managed_root),
        "removed_version_root": str(version_root),
    }


def verify_node_runtime_install(installed_state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    package = installed_state["raw"]["package"]
    for executable in package.get("executables", []):
        path = Path(executable)
        if not path.exists():
            errors.append(f"missing executable: {path}")
            continue
        if not os.access(path, os.X_OK):
            errors.append(f"not executable: {path}")
    return errors


def verify_ollama_runtime_install(installed_state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    package = installed_state["raw"]["package"]
    executable = Path(package["executables"][0])
    library_dir = Path(package.get("library_dir", ""))
    if not executable.exists():
        errors.append(f"missing executable: {executable}")
        return errors
    if not os.access(executable, os.X_OK):
        errors.append(f"not executable: {executable}")
    if package.get("install_mode") == "archive" and not library_dir.exists():
        errors.append(f"missing library dir: {library_dir}")
    env = os.environ.copy()
    if library_dir.exists():
        env["OLLAMA_LIBRARY_PATH"] = str(library_dir)
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{library_dir}:{existing_ld}".rstrip(":")
    result = subprocess.run(
        [str(executable), "--version"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append(f"ollama --version failed: {result.stderr.strip() or result.stdout.strip()}")
    return errors


def verify_ollama_model_install(installed_state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    package = installed_state["raw"]["package"]
    models_path = Path(package["models_path"])
    manifests_dir = models_path / "manifests"
    blobs_dir = models_path / "blobs"
    if not models_path.exists():
        errors.append(f"missing models path: {models_path}")
        return errors
    if not manifests_dir.exists():
        errors.append(f"missing manifests dir: {manifests_dir}")
    if not blobs_dir.exists():
        errors.append(f"missing blobs dir: {blobs_dir}")
    manifest_files = list(manifests_dir.rglob("*")) if manifests_dir.exists() else []
    blob_files = list(blobs_dir.rglob("*")) if blobs_dir.exists() else []
    if manifests_dir.exists() and not any(path.is_file() for path in manifest_files):
        errors.append(f"no manifest files found under: {manifests_dir}")
    if blobs_dir.exists() and not any(path.is_file() for path in blob_files):
        errors.append(f"no blob files found under: {blobs_dir}")
    return errors


def verify_pi_agent_install(installed_state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    package = installed_state["raw"]["package"]
    config_dir = Path(package["config_dir"])
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
    pi_path = Path(package["executables"][0])
    node_runtime_path = Path(package["node_runtime_path"])
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


def verify_managed_files_install(installed_state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    managed_root = Path(installed_state["raw"].get("managed_root", ""))
    state_path = Path(installed_state["state_path"])
    if not managed_root.exists():
        errors.append(f"missing managed root: {managed_root}")
        return errors
    errors.extend(verify_state(managed_root, state_path))
    for executable in installed_state["raw"]["package"].get("executables", []):
        path = Path(executable)
        if not path.exists():
            errors.append(f"missing executable: {path}")
            continue
        if not os.access(path, os.X_OK):
            errors.append(f"not executable: {path}")
    return errors


def build_full_bundle_manifest(
    package_data: dict[str, Any],
    package_manifest: Path,
    store_root: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    files = build_file_index(package_data, package_manifest, store_root, artifact_roots=artifact_roots)
    bundle_id = f'{package_data["package_id"]}-{package_data["version"]}-full'
    return {
        "schema_version": "1",
        "bundle_id": bundle_id,
        "bundle_type": "full",
        "created_at": utc_now(),
        "profile_id": package_data["profile_id"],
        "package": {
            "package_id": package_data["package_id"],
            "version": package_data["version"],
            "install_root": package_data["install_root"],
        },
        "requires": [],
        "ops": [
            {
                "op": "write",
                "install_path": entry["install_path"],
                "sha256": entry["sha256"],
                "size": entry["size"],
                "mode": entry["mode"],
            }
            for entry in files
        ],
        "state": {
            "profile_id": package_data["profile_id"],
            "package_id": package_data["package_id"],
            "package_version": package_data["version"],
            "tracked_files": [
                {
                    "install_path": entry["install_path"],
                    "sha256": entry["sha256"],
                    "size": entry["size"],
                    "mode": entry["mode"],
                }
                for entry in files
            ],
        },
    }


def build_patch_bundle_manifest(
    from_data: dict[str, Any],
    from_manifest: Path,
    to_data: dict[str, Any],
    to_manifest: Path,
    store_root: Path,
    *,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    if from_data["package_id"] != to_data["package_id"]:
        raise ValueError("patch bundles require identical package_id")
    if from_data["profile_id"] != to_data["profile_id"]:
        raise ValueError("patch bundles require identical profile_id")
    if from_data["install_root"] != to_data["install_root"]:
        raise ValueError("patch bundles require identical install_root")

    old_files = {
        entry["install_path"]: entry
        for entry in build_file_index(from_data, from_manifest, store_root, artifact_roots=artifact_roots)
    }
    new_files = {
        entry["install_path"]: entry
        for entry in build_file_index(to_data, to_manifest, store_root, artifact_roots=artifact_roots)
    }

    ops: list[dict[str, Any]] = []
    tracked_files: list[dict[str, Any]] = []

    for path in sorted(new_files):
        new_entry = new_files[path]
        old_entry = old_files.get(path)
        if old_entry is None or old_entry["sha256"] != new_entry["sha256"] or old_entry["mode"] != new_entry["mode"]:
            ops.append(
                {
                    "op": "write",
                    "install_path": path,
                    "sha256": new_entry["sha256"],
                    "size": new_entry["size"],
                    "mode": new_entry["mode"],
                }
            )
        tracked_files.append(
            {
                "install_path": path,
                "sha256": new_entry["sha256"],
                "size": new_entry["size"],
                "mode": new_entry["mode"],
            }
        )

    for path in sorted(old_files):
        if path not in new_files:
            ops.append({"op": "remove", "install_path": path})

    bundle_id = f'{to_data["package_id"]}-{from_data["version"]}-to-{to_data["version"]}-patch'
    return {
        "schema_version": "1",
        "bundle_id": bundle_id,
        "bundle_type": "patch",
        "created_at": utc_now(),
        "profile_id": to_data["profile_id"],
        "package": {
            "package_id": to_data["package_id"],
            "from_version": from_data["version"],
            "to_version": to_data["version"],
            "install_root": to_data["install_root"],
        },
        "requires": [
            {
                "package_id": to_data["package_id"],
                "package_version": from_data["version"],
            }
        ],
        "ops": ops,
        "state": {
            "profile_id": to_data["profile_id"],
            "package_id": to_data["package_id"],
            "package_version": to_data["version"],
            "tracked_files": tracked_files,
        },
    }


def bundle_archive_name(bundle_manifest: dict[str, Any]) -> str:
    return f'{bundle_manifest["bundle_id"]}.tar.gz'


def write_bundle_archive(bundle_manifest: dict[str, Any], store_root: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_path = out_dir / bundle_archive_name(bundle_manifest)
    unique_hashes = sorted(
        {
            op["sha256"]
            for op in bundle_manifest["ops"]
            if op["op"] == "write"
        }
    )

    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        manifest_path = temp_dir / "bundle.json"
        dump_json(manifest_path, bundle_manifest)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(manifest_path, arcname="bundle.json")
            for sha256 in unique_hashes:
                blob_path = blob_store_path(store_root, sha256)
                tar.add(blob_path, arcname=f"blobs/sha256/{sha256}")
    return archive_path


def load_bundle_archive(archive_path: Path) -> tuple[dict[str, Any], tempfile.TemporaryDirectory[str], Path]:
    temp_dir = tempfile.TemporaryDirectory()
    temp_root = Path(temp_dir.name)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(temp_root)
    bundle_manifest = load_json(temp_root / "bundle.json")
    return bundle_manifest, temp_dir, temp_root


def verify_bundle_blobs(bundle_manifest: dict[str, Any], extracted_root: Path) -> None:
    for op in bundle_manifest["ops"]:
        if op["op"] != "write":
            continue
        blob_path = extracted_root / "blobs" / "sha256" / op["sha256"]
        if not blob_path.exists():
            raise ValueError(f"missing bundle blob: {op['sha256']}")
        actual = sha256_file(blob_path)
        if actual != op["sha256"]:
            raise ValueError(f"bundle blob hash mismatch: {op['sha256']}")


def apply_bundle(bundle_manifest: dict[str, Any], extracted_root: Path, target_root: Path, state_path: Path) -> dict[str, Any]:
    verify_bundle_blobs(bundle_manifest, extracted_root)
    target_root.mkdir(parents=True, exist_ok=True)
    for op in bundle_manifest["ops"]:
        install_path = target_root / op["install_path"]
        if op["op"] == "write":
            install_path.parent.mkdir(parents=True, exist_ok=True)
            blob_path = extracted_root / "blobs" / "sha256" / op["sha256"]
            shutil.copy2(blob_path, install_path)
            os.chmod(install_path, int(op["mode"], 8))
        elif op["op"] == "remove":
            if install_path.exists():
                install_path.unlink()
        else:
            raise ValueError(f"unsupported op: {op['op']}")

    state = {
        "schema_version": "1",
        "updated_at": utc_now(),
        "bundle": {
            "bundle_id": bundle_manifest["bundle_id"],
            "bundle_type": bundle_manifest["bundle_type"],
            "profile_id": bundle_manifest["profile_id"],
        },
        "package": bundle_manifest["state"] | {
            "install_root": bundle_manifest["package"]["install_root"],
        },
        "history": append_history(state_path, bundle_manifest),
    }
    dump_json(state_path, state)
    return state


def append_history(state_path: Path, bundle_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    if state_path.exists():
        current = load_json(state_path)
        history.extend(current.get("history", []))
    history.append(
        {
            "bundle_id": bundle_manifest["bundle_id"],
            "bundle_type": bundle_manifest["bundle_type"],
            "applied_at": utc_now(),
        }
    )
    return history


def verify_state(target_root: Path, state_path: Path, *, check_modes: bool = False) -> list[str]:
    state = load_json(state_path)
    errors: list[str] = []
    for tracked in state["package"]["tracked_files"]:
        install_path = target_root / tracked["install_path"]
        if not install_path.exists():
            errors.append(f"missing file: {tracked['install_path']}")
            continue
        actual_hash = sha256_file(install_path)
        if actual_hash != tracked["sha256"]:
            errors.append(f"hash mismatch: {tracked['install_path']}")
        if check_modes:
            actual_mode = format(install_path.stat().st_mode & 0o777, "04o")
            if actual_mode != tracked["mode"]:
                errors.append(f"mode mismatch: {tracked['install_path']} expected={tracked['mode']} actual={actual_mode}")
    return errors
