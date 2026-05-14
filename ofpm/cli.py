from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
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
from ofpm.core import (
    dump_json,
    find_installed_state,
    install_node_runtime,
    install_managed_files_package,
    install_ollama_model_bundle,
    install_ollama_runtime,
    install_pi_agent,
    installed_states,
    list_available_packages,
    load_artifact_roots,
    load_json,
    managed_state_root,
    package_summary_from_manifest,
    repo_repos_config_path,
    remove_managed_payload,
    remove_node_runtime,
    registered_repos,
    save_repos_config,
    sync_managed_state_db,
    user_repos_config_path,
    verify_package_sources,
    verify_node_runtime_install,
    verify_ollama_model_install,
    verify_ollama_runtime_install,
    verify_pi_agent_install,
    verify_managed_files_install,
    verify_state,
)
from ofpm.modules import render_package_modulefile, render_package_shell_env
from ofpm.state_db import (
    list_ownership_entries,
    list_receipts,
    managed_history_path,
    managed_ownership_root,
    managed_receipts_root,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_repo_path(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / "repos" / "main"


def effective_registered_repos(root: Path | None = None) -> dict[str, str]:
    base = root or repo_root()
    repos = registered_repos(base)
    if repos:
        return repos
    return {"main": str(default_repo_path(base))}


def primary_repo_path(root: Path | None = None) -> Path:
    base = root or repo_root()
    repos = effective_registered_repos(base)
    preferred = repos.get("main")
    if preferred:
        return Path(preferred).expanduser().resolve()
    first_repo = next(iter(sorted(repos.items())))[1]
    return Path(first_repo).expanduser().resolve()


def managed_root(root_kind: str) -> Path:
    if root_kind == "system":
        return Path("/opt/ofpm")
    if root_kind == "user":
        home = Path(os.environ.get("HOME", "~")).expanduser()
        return home / ".ofpm"
    raise ValueError(f"unsupported root kind: {root_kind}")


def effective_managed_root(args: argparse.Namespace) -> Path:
    if getattr(args, "root_path", None):
        return Path(args.root_path).resolve()
    return managed_root(getattr(args, "root", "user"))


def managed_roots_for_query(args: argparse.Namespace) -> list[tuple[str, Path]]:
    if getattr(args, "all_roots", False):
        return [("user", managed_root("user")), ("system", managed_root("system"))]
    if getattr(args, "root_path", None):
        return [(getattr(args, "root", "user"), Path(args.root_path).resolve())]
    root_kind = getattr(args, "root", "user")
    return [(root_kind, managed_root(root_kind))]


def installed_states_for_query(args: argparse.Namespace) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for root_kind, managed in managed_roots_for_query(args):
        for item in installed_states(managed_state_root(managed)):
            entry = dict(item)
            entry["selected_root_kind"] = root_kind
            entry["managed_root"] = str(managed)
            entry["recorded_root_kind"] = item["raw"].get("root_kind", "")
            combined.append(entry)
    return combined


def resolve_installed_state_for_action(args: argparse.Namespace, package_id: str) -> tuple[Path, dict[str, Any]] | None:
    matches = [item for item in installed_states_for_query(args) if item["package_id"] == package_id]
    if not matches:
        return None
    if len(matches) == 1:
        item = matches[0]
        return Path(item["managed_root"]), item
    print(f"package is installed in multiple roots: {package_id}")
    for item in sorted(matches, key=lambda current: (current["selected_root_kind"], current["managed_root"])):
        print(
            " - "
            f"root={item['selected_root_kind']} "
            f"managed_root={item['managed_root']} "
            f"version={item['package_version']} "
            f"state={item['state_path']}"
        )
    print("choose one root explicitly with --root user or --root system")
    return None


def any_installed_state(package_id: str) -> bool:
    for root_kind in ["user", "system"]:
        if find_installed_state(managed_state_root(managed_root(root_kind)), package_id) is not None:
            return True
    return False


def effective_artifact_roots() -> dict[str, str]:
    return load_artifact_roots(repo_root())


def sources_config_path(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / "local" / "sources.json"


def stored_sources(root: Path | None = None) -> dict[str, dict[str, str]]:
    path = sources_config_path(root)
    if not path.exists():
        return {}
    return load_json(path)


def save_sources_config(path: Path, sources: dict[str, dict[str, str]]) -> None:
    dump_json(path, dict(sorted(sources.items())))


def launcher_script_text(*, python_executable: str, source_root: Path) -> str:
    quoted_python = python_executable.replace('"', '\\"')
    quoted_root = str(source_root).replace('"', '\\"')
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f'export PYTHONPATH="{quoted_root}${{PYTHONPATH:+:$PYTHONPATH}}"',
            f'exec "{quoted_python}" -m ofpm "$@"',
            "",
        ]
    )


def resolve_registered_repo_path(repo_id: str, root: Path | None = None) -> Path:
    repos = effective_registered_repos(root or repo_root())
    if repo_id not in repos:
        raise ValueError(f"repo not found: {repo_id}")
    return Path(repos[repo_id]).expanduser().resolve()


def detect_source_kind(path: Path) -> str:
    if path.is_dir():
        return "dir"
    if path.is_file():
        return "file"
    raise ValueError(f"unsupported source path: {path}")


def relpath_posix(target: Path, start: Path) -> str:
    return os.path.relpath(target, start).replace(os.sep, "/")


def source_file_count(path: Path) -> int:
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def resolve_repo_data_path(repo_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    project_candidate = (repo_root() / path).resolve()
    if project_candidate.exists():
        return project_candidate
    repo_candidate = (repo_path / path).resolve()
    if repo_candidate.exists():
        return repo_candidate
    return project_candidate


def build_source_package_manifest(
    source_name: str,
    source_path: Path,
    artifact_root: Path,
    manifest_root: Path,
    *,
    package_id: str,
    version: str,
    profile_id: str,
    install_root: str,
    description: str,
) -> dict[str, Any]:
    metadata = {
        "description": description,
        "source_kind": "repo-internal",
        "source_name": source_name,
        "origin_path": str(source_path),
        "origin_relroot": relpath_posix(artifact_root, manifest_root),
    }
    if source_path.is_dir():
        payload_root = artifact_root / "payload"
        source_relpath = relpath_posix(payload_root, manifest_root)
        files: list[dict[str, Any]] = [
            {
                "source_dir": source_relpath,
                "target_dir": "",
                "file_count_hint": source_file_count(source_path),
            }
        ]
    else:
        copied_file = artifact_root / source_path.name
        source_relpath = relpath_posix(copied_file, manifest_root)
        files = [
            {
                "source": source_relpath,
                "target": source_path.name,
            }
        ]
    return {
        "schema_version": "1",
        "package_id": package_id,
        "version": version,
        "profile_id": profile_id,
        "install_root": install_root,
        "depends": [],
        "metadata": metadata,
        "files": files,
    }


def import_local_source_package(
    repo_path: Path,
    source_name: str,
    source_record: dict[str, str],
    *,
    package_id: str,
    version: str,
    profile_id: str,
    install_root: str,
    description: str,
) -> tuple[Path, Path]:
    source_path = Path(source_record["path"]).expanduser().resolve()
    manifest_root = repo_path / "catalog" / "packages" / package_id / version
    manifest_path = manifest_root / "package.json"
    artifact_root = repo_path / "artifacts" / "ofpm" / package_id / version
    if manifest_path.exists():
        raise ValueError(f"package manifest already exists: {manifest_path}")
    if artifact_root.exists():
        raise ValueError(f"package artifact root already exists: {artifact_root}")

    artifact_root.parent.mkdir(parents=True, exist_ok=True)
    if source_record["kind"] == "dir":
        shutil.copytree(source_path, artifact_root / "payload", dirs_exist_ok=False)
    else:
        artifact_root.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source_path, artifact_root / source_path.name)

    manifest = build_source_package_manifest(
        source_name,
        source_path,
        artifact_root,
        manifest_root,
        package_id=package_id,
        version=version,
        profile_id=profile_id,
        install_root=install_root,
        description=description,
    )
    dump_json(manifest_path, manifest)
    return manifest_path, artifact_root


def build_apt_package_manifest(
    repo_path: Path,
    provider_manifest_path: Path,
    snapshot: dict[str, Any],
    *,
    package_id: str,
    profile_id: str,
    install_root: str,
    description: str,
) -> dict[str, Any]:
    manifest_root = repo_path / "catalog" / "packages" / package_id / snapshot["package_version"]
    artifact_root = resolve_repo_data_path(repo_path, snapshot["artifact_root"])
    files: list[dict[str, Any]] = []
    metadata_package_path = artifact_root / "metadata" / "package.json"
    files.append(
        {
            "source": relpath_posix(metadata_package_path, manifest_root),
            "target": "metadata/package.json",
            "mode": "0644",
        }
    )
    for package in snapshot.get("packages", []):
        package_path = resolve_repo_data_path(repo_path, str(package["path"]))
        files.append(
            {
                "source": relpath_posix(package_path, manifest_root),
                "target": f"pool/{package['filename']}",
                "mode": "0644",
            }
        )
    return {
        "schema_version": "1",
        "package_id": package_id,
        "version": snapshot["package_version"],
        "profile_id": profile_id,
        "install_root": install_root,
        "depends": [],
        "metadata": {
            "description": description,
            "source_kind": "provider-apt",
            "provider": "apt",
            "provider_manifest": str(provider_manifest_path),
            "artifact_root": str(artifact_root),
        },
        "files": files,
    }


def available_packages_with_repo() -> list[dict[str, object]]:
    root = repo_root()
    artifact_roots = effective_artifact_roots()
    repos = effective_registered_repos(root)

    packages: list[dict[str, object]] = []
    for repo_id, repo_path_raw in sorted(repos.items()):
        repo_path = Path(repo_path_raw).expanduser().resolve()
        catalog_root = repo_path / "catalog"
        if not catalog_root.exists():
            continue
        for item in list_available_packages(catalog_root, artifact_roots):
            package = dict(item)
            package["repo_id"] = repo_id
            package["repo_path"] = str(repo_path)
            packages.append(package)
    return sorted(
        packages,
        key=lambda item: (
            str(item["package_id"]),
            str(item["version"]),
            str(item["repo_id"]),
        ),
    )


def package_manifests_with_repo() -> list[dict[str, str]]:
    root = repo_root()
    repos = effective_registered_repos(root)
    manifests: list[dict[str, str]] = []
    for repo_id, repo_path_raw in sorted(repos.items()):
        repo_path = Path(repo_path_raw).expanduser().resolve()
        for manifest_path in sorted((repo_path / "catalog" / "packages").glob("*/*/package.json")):
            manifests.append(
                {
                    "repo_id": repo_id,
                    "repo_path": str(repo_path),
                    "manifest": str(manifest_path),
                }
            )
    return manifests


def find_registered_package_manifest(package_id: str, version: str | None = None) -> dict[str, str] | None:
    matches: list[dict[str, str]] = []
    for entry in package_manifests_with_repo():
        manifest_path = Path(entry["manifest"])
        data = load_json(manifest_path)
        if data["package_id"] != package_id:
            continue
        if version is not None and data["version"] != version:
            continue
        matches.append(
            {
                "repo_id": entry["repo_id"],
                "repo_path": entry["repo_path"],
                "manifest": str(manifest_path),
                "version": data["version"],
            }
        )
    if not matches:
        return None
    return sorted(matches, key=lambda item: item["version"])[-1]


def resolve_registered_package_specs(package_specs: list[str]) -> list[tuple[str, dict[str, str]]]:
    resolved: list[tuple[str, dict[str, str]]] = []
    seen_specs: set[str] = set()
    for spec in package_specs:
        if spec in seen_specs:
            continue
        seen_specs.add(spec)
        if "@" in spec:
            package_id, version = spec.split("@", 1)
        else:
            package_id, version = spec, None
        manifest_entry = find_registered_package_manifest(package_id, version)
        if manifest_entry is None:
            raise ValueError(f"package not found: {spec}")
        resolved.append((spec, manifest_entry))
    return resolved


def apt_snapshots_with_repo() -> list[dict[str, object]]:
    root = repo_root()
    repos = effective_registered_repos(root)
    snapshots: list[dict[str, object]] = []
    for repo_id, repo_path_raw in sorted(repos.items()):
        repo_path = Path(repo_path_raw).expanduser().resolve()
        for item in list_apt_packages(repo_path):
            snapshot = dict(item)
            snapshot["repo_id"] = repo_id
            snapshot["repo_path"] = str(repo_path)
            snapshots.append(snapshot)
    return sorted(
        snapshots,
        key=lambda item: (
            str(item["package_name"]),
            str(item["package_version"]),
            str(item["repo_id"]),
        ),
    )


def offline_strict_enabled() -> bool:
    value = os.environ.get("OFPM_OFFLINE_STRICT", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def require_offline_target_mode(command_name: str) -> None:
    if not offline_strict_enabled():
        print(f"warning: {command_name} is running with OFPM_OFFLINE_STRICT=0")
        print("warning: target-side commands are intended to remain offline-only")


def cmd_init(args: argparse.Namespace) -> int:
    root = repo_root()
    for rel in [
        "local",
        "repos/main/catalog/packages",
        "repos/main/catalog/apt",
        "repos/main/artifacts/ofpm",
        "repos/main/artifacts/apt",
        "repos/main/profiles",
        "repos/main/schemas",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    print(f"initialized scaffold under {root}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    if args.installed:
        installed = installed_states_for_query(args)
        if args.pattern:
            installed = [
                item
                for item in installed
                if args.pattern.lower() in item["package_id"].lower()
            ]
        if args.json:
            print_json({"installed": installed})
            return 0
        if not installed:
            queried_roots = ", ".join(
                f"{root_kind}={managed}"
                for root_kind, managed in managed_roots_for_query(args)
            )
            print(f"no installed packages recorded for roots: {queried_roots}")
            return 0
        queried_roots = ", ".join(
            f"{root_kind}={managed}"
            for root_kind, managed in managed_roots_for_query(args)
        )
        print(f"queried roots: {queried_roots}")
        print(f"installed package count: {len(installed)}")
        for item in sorted(installed, key=lambda current: (current["package_id"], current["selected_root_kind"])):
            print(
                " - "
                f"{item['package_id']} {item['package_version']} "
                f"[root={item['selected_root_kind']}] "
                f"[managed_root={item['managed_root']}] "
                f"[profile={item['profile_id']}] "
                f"[install_root={item['install_root']}] "
                f"[tracked_files={item['tracked_file_count']}]"
            )
            if args.verbose:
                print(f"   state: {item['state_path']}")
                print(f"   origin: {item['bundle_id']} ({item['bundle_type']})")
        return 0

    available = available_packages_with_repo()
    if not args.all:
        available = [item for item in available if item.get("available", True)]
    if args.pattern:
        available = [
            item
            for item in available
            if args.pattern.lower() in item["package_id"].lower()
        ]
    if args.json:
        print_json({"packages": available})
        return 0

    if not available:
        print("no packages found in registered repos")
        return 0

    print("package sources: registered repos")
    print(f"package count: {len(available)}")
    for package in available:
        print(
            " - "
            f"{package['package_id']} {package['version']} "
            f"[repo={package['repo_id']}] "
            f"[profile={package['profile_id']}] "
            f"[install_root={package['install_root']}] "
            f"[files={package['file_count']}] "
            f"[available={'yes' if package.get('available', True) else 'no'}]"
        )
        if args.verbose:
            if package["description"]:
                print(f"   description: {package['description']}")
            print(f"   repo path: {package['repo_path']}")
            print(f"   manifest: {package['manifest']}")
            if package.get("availability_error"):
                print(f"   availability error: {package['availability_error']}")
            if not package.get("available", True):
                print(f"   missing sources: {package.get('missing_count', 0)}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    artifact_roots = effective_artifact_roots()
    manifest_entry = find_registered_package_manifest(args.package, args.version)
    if manifest_entry is None:
        print(f"package not found: {args.package}")
        return 1
    manifest_path = Path(manifest_entry["manifest"])
    package = package_summary_from_manifest(
        manifest_path,
        include_files=args.files,
        artifact_roots=artifact_roots,
    )
    installed = find_installed_state(managed_state_root(effective_managed_root(args)), package["package_id"])

    if args.json:
        print_json({"package": package, "installed": installed})
        return 0

    print(f"package: {package['package_id']}")
    print(f"version: {package['version']}")
    print(f"repo: {manifest_entry['repo_id']}")
    print(f"repo path: {manifest_entry['repo_path']}")
    print(f"profile: {package['profile_id']}")
    print(f"install root: {package['install_root']}")
    print(f"manifest: {package['manifest']}")
    if package["description"]:
        print(f"description: {package['description']}")
    print(f"file count: {package['file_count']}")
    print(f"available: {'yes' if package['available'] else 'no'}")
    if package.get("availability_error"):
        print(f"availability error: {package['availability_error']}")
    if package["missing_count"]:
        print(f"missing sources: {package['missing_count']}")
    if package["depends"]:
        print("dependencies:")
        for dep in package["depends"]:
            dep_version = dep.get("version", "*")
            dep_required = "required" if dep.get("required", True) else "optional"
            line = f" - {dep['package_id']} {dep_version} [{dep_required}]"
            if dep.get("reason"):
                line += f" {dep['reason']}"
            print(line)
    if installed:
        print("installed: yes")
        print(f"installed version: {installed['package_version']}")
        print(f"installed state: {installed['state_path']}")
        print(f"installed origin: {installed['bundle_id']} ({installed['bundle_type']})")
    else:
        print("installed: no")

    if package["missing_count"]:
        print("missing artifact sources:")
        for source in package["missing_sources"][:20]:
            print(f" - {source}")
        if package["missing_count"] > 20:
            print(f" - ... {package['missing_count'] - 20} more")

    if args.files:
        print("files:")
        for file_item in package["files"]:
            print(f" - {file_item['target']} <= {file_item['source']}")
    return 0


def cmd_verify_source(args: argparse.Namespace) -> int:
    manifest_entry = find_registered_package_manifest(args.package, args.version)
    if manifest_entry is None:
        print(f"package not found: {args.package}")
        return 1
    manifest_path = Path(manifest_entry["manifest"])
    result = verify_package_sources(
        manifest_path,
        artifact_roots=effective_artifact_roots(),
    )
    print(f"verify-source package: {result['package_id']}")
    print(f" - version: {result['version']}")
    print(f" - manifest: {result['manifest']}")
    print(f" - declared source paths: {result['declared_source_count']}")
    print(f" - expanded files: {result['expanded_file_count']}")
    if result["missing_sources"]:
        print(f" - missing source paths: {len(result['missing_sources'])}")
        for path in result["missing_sources"][:20]:
            print(f"   {path}")
        if len(result["missing_sources"]) > 20:
            print(f"   ... {len(result['missing_sources']) - 20} more")
    if result["missing_files"]:
        print(f" - missing expanded files: {len(result['missing_files'])}")
        for path in result["missing_files"][:20]:
            print(f"   {path}")
        if len(result["missing_files"]) > 20:
            print(f"   ... {len(result['missing_files']) - 20} more")
    if result["ok"]:
        print(" - result: verified")
        return 0
    print(" - result: failed")
    return 1


def cmd_install(args: argparse.Namespace) -> int:
    require_offline_target_mode("install")
    artifact_roots = effective_artifact_roots()
    manifest_entry = find_registered_package_manifest(args.package, args.version)
    if manifest_entry is None:
        print(f"package not found: {args.package}")
        return 1
    manifest_path = Path(manifest_entry["manifest"])
    package = package_summary_from_manifest(manifest_path, artifact_roots=artifact_roots)
    managed = effective_managed_root(args)
    package_data = load_json(manifest_path)
    if package["package_id"] == "node-runtime":
        state = install_node_runtime(
            managed,
            manifest_path,
            package_data,
            root_kind=args.root,
            artifact_roots=artifact_roots,
        )
        print(f"installed package: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(f" - current path: {state['package']['current_path']}")
        print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
        return 0
    if package["package_id"] == "ollama-runtime":
        state = install_ollama_runtime(
            managed,
            manifest_path,
            package_data,
            root_kind=args.root,
            artifact_roots=artifact_roots,
        )
        print(f"installed package: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(f" - current path: {state['package']['current_path']}")
        print(f" - library dir: {state['package']['library_dir']}")
        print(f" - install mode: {state['package']['install_mode']}")
        print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
        return 0
    if package["package_id"] == "pi-agent":
        state = install_pi_agent(
            managed,
            manifest_path,
            package_data,
            root_kind=args.root,
            artifact_roots=artifact_roots,
        )
        print(f"installed package: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(f" - current path: {state['package']['current_path']}")
        print(f" - config dir: {state['package']['config_dir']}")
        print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
        return 0
    if package["package_id"].startswith("ollama-model-"):
        state = install_ollama_model_bundle(
            managed,
            manifest_path,
            package_data,
            root_kind=args.root,
            artifact_roots=artifact_roots,
        )
        print(f"installed package: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(f" - current path: {state['package']['current_path']}")
        print(f" - models path: {state['package']['models_path']}")
        print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
        return 0
    print(f"install plan for {package['package_id']} {package['version']}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    print(f" - managed root: {managed}")
    print(f" - check catalog manifest: {package['manifest']}")
    print(f" - check target profile compatibility: expected {package['profile_id']}")
    print(f" - install root policy: {package['install_root']}")
    print(f" - package file count: {package['file_count']}")
    state = install_managed_files_package(
        managed,
        manifest_path,
        package_data,
        root_kind=args.root,
        artifact_roots=artifact_roots,
    )
    print(f"installed package: {package['package_id']} {package['version']}")
    print(f" - managed root: {managed}")
    print(f" - current path: {state['package']['current_path']}")
    print(f" - tracked files: {len(state['package']['tracked_files'])}")
    print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    require_offline_target_mode("upgrade")
    resolved = resolve_installed_state_for_action(args, args.package)
    installed = resolved[1] if resolved is not None else None
    manifest_entry = find_registered_package_manifest(args.package, args.version)
    if manifest_entry is None:
        print(f"package not found: {args.package}")
        return 1
    manifest_path = Path(manifest_entry["manifest"])
    package = package_summary_from_manifest(manifest_path, artifact_roots=effective_artifact_roots())
    print(f"upgrade plan for {package['package_id']}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    if installed:
        print(f" - installed version: {installed['package_version']}")
        print(f" - installed state: {installed['state_path']}")
    else:
        print(" - installed version: not recorded")
    print(f" - target version: {package['version']}")
    print(f" - target profile: {package['profile_id']}")
    print(" - action: repo package upgrade planning only for now")
    print("next implementation: compare installed state against repo package version and apply upgrade policy")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    require_offline_target_mode("remove")
    resolved = resolve_installed_state_for_action(args, args.package)
    if resolved is None:
        if not any_installed_state(args.package):
            print(f"package not installed: {args.package}")
        return 1
    managed, installed = resolved
    if installed["package_id"] == "node-runtime":
        result = remove_node_runtime(managed, installed)
        print(f"removed package: {result['package_id']} {result['package_version']}")
        print(f" - managed root: {result['managed_root']}")
        print(f" - removed version root: {result['removed_version_root']}")
        return 0
    if installed["package_id"] in {"ollama-runtime", "pi-agent"} or installed["package_id"].startswith("ollama-model-"):
        result = remove_managed_payload(managed, installed)
        print(f"removed package: {result['package_id']} {result['package_version']}")
        print(f" - managed root: {result['managed_root']}")
        print(f" - removed version root: {result['removed_version_root']}")
        return 0
    if installed["raw"].get("install_type") == "managed-install" and installed["raw"]["package"].get("version_root"):
        result = remove_managed_payload(managed, installed)
        print(f"removed package: {result['package_id']} {result['package_version']}")
        print(f" - managed root: {result['managed_root']}")
        print(f" - removed version root: {result['removed_version_root']}")
        return 0
    print(f"remove plan for {args.package}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    print(f" - installed version: {installed['package_version']}")
    print(f" - install root: {installed['install_root']}")
    print(f" - tracked files: {installed['tracked_file_count']}")
    print(f" - state file: {installed['state_path']}")
    print(" - action: removal planning only for now")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    require_offline_target_mode("verify")
    resolved = resolve_installed_state_for_action(args, args.package)
    if resolved is None:
        if not any_installed_state(args.package):
            print(f"package not installed: {args.package}")
        return 1
    managed, installed = resolved
    if installed["package_id"] == "node-runtime":
        errors = verify_node_runtime_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if installed["package_id"] == "ollama-runtime":
        errors = verify_ollama_runtime_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if installed["package_id"] == "pi-agent":
        errors = verify_pi_agent_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if installed["package_id"].startswith("ollama-model-"):
        errors = verify_ollama_model_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if installed["raw"].get("install_type") == "managed-install" and installed["raw"]["package"].get("tracked_files"):
        errors = verify_managed_files_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if not args.target_root:
        print("verify requires --target-root for this package type")
        return 1
    target_root = Path(args.target_root).resolve()
    errors = verify_state(
        target_root.resolve(),
        Path(installed["state_path"]).resolve(),
        check_modes=args.strict_modes,
    )
    print(f"verify package: {args.package}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    print(f" - state file: {installed['state_path']}")
    print(f" - target root: {target_root.resolve()}")
    print(f" - tracked files: {installed['tracked_file_count']}")
    if errors:
        print(" - result: failed")
        for error in errors:
            print(f"   {error}")
        return 1
    print(" - result: verified")
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    root_entries: list[dict[str, Any]] = []
    for root_kind, managed in managed_roots_for_query(args):
        sync_result = sync_managed_state_db(managed)
        installed = installed_states(managed_state_root(managed))
        receipts = list_receipts(managed)
        ownership_entries = list_ownership_entries(managed)
        root_entries.append(
            {
                "root_kind": root_kind,
                "managed_root": str(managed),
                "sync": sync_result,
                "installed": installed,
                "receipts": receipts,
                "ownership": ownership_entries,
                "history_path": str(managed_history_path(managed)),
            }
        )
    if args.json:
        print_json({"roots": root_entries})
        return 0
    for index, entry in enumerate(root_entries):
        managed = Path(entry["managed_root"])
        installed = entry["installed"]
        receipts = entry["receipts"]
        ownership_entries = entry["ownership"]
        sync_result = entry["sync"]
        if index:
            print()
        print(f"root: {entry['root_kind']}")
        print(f"managed root: {managed}")
        print(f"state root: {managed_state_root(managed)}")
        print(f"receipt root: {managed_receipts_root(managed)}")
        print(f"ownership root: {managed_ownership_root(managed)}")
        print(f"history file: {managed_history_path(managed)}")
        if not installed:
            print("installed package count: 0")
            print(f"receipt count: {len(receipts)}")
            print(f"ownership entry count: {len(ownership_entries)}")
            continue
        if sync_result["created_receipts"]:
            print(f"synced legacy receipts: {sync_result['created_receipts']}")
        if sync_result.get("failed_receipts"):
            print(f"receipt sync failures: {sync_result['failed_receipts']}")
        print(f"installed package count: {len(installed)}")
        print(f"receipt count: {len(receipts)}")
        print(f"ownership entry count: {len(ownership_entries)}")
        for item in installed:
            print(f" - {item['package_id']} {item['package_version']} [{item['updated_at']}]")
            print(f"   install_root: {item['install_root']}")
            print(f"   profile: {item['profile_id']}")
            print(f"   state: {item['state_path']}")
            print(f"   origin: {item['bundle_id']} ({item['bundle_type']})")


def cmd_env(args: argparse.Namespace) -> int:
    if args.subject == "package":
        if not args.package_name:
            print("env package requires a package name")
            return 1
        managed = effective_managed_root(args)
        installed = find_installed_state(managed_state_root(managed), args.package_name)
        if installed is None:
            print(f"package not installed: {args.package_name}")
            return 1
        if args.format == "modulefile":
            print(render_package_modulefile(managed, installed["raw"]), end="")
            return 0
        print(render_package_shell_env(managed, installed["raw"]), end="")
        return 0
    if args.subject:
        print(f"unsupported env subject: {args.subject}")
        return 1

    root = effective_managed_root(args)
    bin_dir = root / "bin"
    payload_bin_dirs = [
        path
        for path in [
            root / "payloads" / "node-runtime" / "current" / "bin",
            root / "payloads" / "pi-agent" / "current" / "bin",
            root / "payloads" / "ollama-runtime" / "current" / "bin",
        ]
        if path.exists()
    ]
    path_entries = [path for path in [bin_dir, *payload_bin_dirs] if path.exists()]

    export_lines = [f'export OFPM_ROOT="{root}"']
    if path_entries:
        export_lines.append(f'export PATH="{":".join(str(path) for path in path_entries)}:$PATH"')

    if args.export:
        for line in export_lines:
            print(line)
        return 0

    print(f"root kind: {args.root}")
    print(f"managed root: {root}")
    print("path entries:")
    for entry in path_entries:
        print(f" - {entry}")
    print("shell snippet:")
    for line in export_lines:
        print(f"  {line}")
    print("usage:")
    print(f" - one-shot: eval \"$(python3 -m ofpm env --root {args.root} --export)\"")
    print(f" - inspect only: python3 -m ofpm env --root {args.root}")
    print(f" - package bash: python3 -m ofpm env package <package> --root {args.root}")
    print(f" - package modulefile: python3 -m ofpm env package <package> --root {args.root} --format modulefile")
    print("notes:")
    print(" - this does not modify your shell automatically")
    print(" - edit the snippet before adding it to ~/.bashrc if you want a different PATH order")
    return 0


def cmd_source_list(args: argparse.Namespace) -> int:
    sources = stored_sources()
    if args.json:
        print_json({"config_path": str(sources_config_path()), "sources": sources})
        return 0
    if not sources:
        print(f"no registered sources in {sources_config_path()}")
        return 0
    print(f"source config: {sources_config_path()}")
    print("registered sources:")
    for name, item in sorted(sources.items()):
        print(f" - {name} [{item['kind']}] {item['path']}")
    return 0


def cmd_source_show(args: argparse.Namespace) -> int:
    sources = stored_sources()
    name = args.source_name.strip().lower()
    if name not in sources:
        print(f"source not found: {name}")
        return 1
    item = sources[name]
    path = Path(item["path"])
    exists = path.exists()
    file_count = source_file_count(path) if exists else 0
    if args.json:
        print_json(
            {
                "name": name,
                "kind": item["kind"],
                "path": item["path"],
                "added_at": item.get("added_at", ""),
                "exists": exists,
                "file_count": file_count,
            }
        )
        return 0
    print(f"source: {name}")
    print(f" - kind: {item['kind']}")
    print(f" - path: {item['path']}")
    print(f" - added at: {item.get('added_at', '')}")
    print(f" - exists: {'yes' if exists else 'no'}")
    print(f" - file count: {file_count}")
    return 0 if exists else 1


def cmd_source_add(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"source path not found: {path}")
        return 1
    name = args.source_name.strip().lower()
    sources = stored_sources()
    sources[name] = {
        "name": name,
        "path": str(path),
        "kind": detect_source_kind(path),
        "added_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    save_sources_config(sources_config_path(), sources)
    print(f"registered source: {name}")
    print(f" - kind: {sources[name]['kind']}")
    print(f" - path: {path}")
    print(f" - config: {sources_config_path()}")
    return 0


def cmd_source_remove(args: argparse.Namespace) -> int:
    sources = stored_sources()
    name = args.source_name.strip().lower()
    if name not in sources:
        print(f"source not found: {name}")
        return 1
    removed = sources.pop(name)
    save_sources_config(sources_config_path(), sources)
    print(f"removed source: {name}")
    print(f" - path: {removed['path']}")
    print(f" - config: {sources_config_path()}")
    return 0


def cmd_source_verify(args: argparse.Namespace) -> int:
    sources = stored_sources()
    name = args.source_name.strip().lower()
    if name not in sources:
        print(f"source not found: {name}")
        return 1
    item = sources[name]
    path = Path(item["path"])
    kind = item["kind"]
    errors: list[str] = []
    if not path.exists():
        errors.append("path does not exist")
    elif kind == "dir" and not path.is_dir():
        errors.append("stored kind is dir but path is not a directory")
    elif kind == "file" and not path.is_file():
        errors.append("stored kind is file but path is not a file")
    print(f"verify source: {name}")
    print(f" - kind: {kind}")
    print(f" - path: {path}")
    print(f" - file count: {source_file_count(path) if path.exists() else 0}")
    if errors:
        print(" - result: failed")
        for error in errors:
            print(f"   {error}")
        return 1
    print(" - result: verified")
    return 0


def cmd_install_cli(args: argparse.Namespace) -> int:
    raw_output = args.output or "ofpm"
    output_path = Path(raw_output).expanduser().resolve()
    python_executable = args.python or sys.executable
    source_root = Path(args.source_root).expanduser().resolve() if args.source_root else repo_root()
    if output_path.exists() and output_path.is_dir():
        print(f"launcher path is a directory: {output_path}")
        print("choose a file path, for example: install-cli ./bin/ofpm")
        return 1
    if output_path.exists() and not args.force:
        print(f"launcher already exists: {output_path}")
        print("use --force to overwrite it")
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = launcher_script_text(
        python_executable=python_executable,
        source_root=source_root,
    )
    output_path.write_text(content, encoding="utf-8")
    os.chmod(output_path, 0o755)
    print("installed ofpm launcher")
    print("closest existing model: this behaves more like `make install` than `apt install`")
    print(f" - output: {output_path}")
    print(f" - python: {python_executable}")
    print(f" - source root: {source_root}")
    print(f" - run: {output_path} --help")
    return 0


def repo_config_path(args: argparse.Namespace) -> Path:
    if args.scope == "user":
        return user_repos_config_path()
    if args.scope == "repo":
        return repo_repos_config_path(repo_root())
    raise ValueError(f"unsupported repo scope: {args.scope}")


def stored_repos(args: argparse.Namespace) -> dict[str, str]:
    path = repo_config_path(args)
    if not path.exists():
        return {}
    return load_json(path)


def cmd_repo_list(args: argparse.Namespace) -> int:
    path = repo_config_path(args)
    repos = stored_repos(args)
    if args.json:
        print_json({"scope": args.scope, "config_path": str(path), "repos": repos})
        return 0
    if not repos:
        print(f"no registered repos in {path}")
        return 0
    print(f"repo scope: {args.scope}")
    print(f"config path: {path}")
    print("registered repos:")
    for repo_id, repo_path in sorted(repos.items()):
        print(f" - {repo_id}: {repo_path}")
    return 0


def cmd_repo_add(args: argparse.Namespace) -> int:
    path = repo_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    repo_path = str(Path(args.path).expanduser().resolve())
    repos[repo_id] = repo_path
    save_repos_config(path, repos)
    print(f"registered repo: {repo_id}")
    print(f" - path: {repo_path}")
    print(f" - scope: {args.scope}")
    print(f" - config: {path}")
    return 0


def cmd_repo_remove(args: argparse.Namespace) -> int:
    path = repo_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    if repo_id not in repos:
        print(f"repo not found: {repo_id}")
        print(f" - scope: {args.scope}")
        print(f" - config: {path}")
        return 1
    removed_path = repos.pop(repo_id)
    save_repos_config(path, repos)
    print(f"removed repo: {repo_id}")
    print(f" - path: {removed_path}")
    print(f" - scope: {args.scope}")
    print(f" - config: {path}")
    return 0


def cmd_repo_show(args: argparse.Namespace) -> int:
    path = repo_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    if repo_id not in repos:
        print(f"repo not found: {repo_id}")
        print(f" - scope: {args.scope}")
        print(f" - config: {path}")
        return 1
    print(f"repo: {repo_id}")
    print(f" - path: {repos[repo_id]}")
    print(f" - scope: {args.scope}")
    print(f" - config: {path}")
    return 0


def cmd_repo_import(args: argparse.Namespace) -> int:
    repo_id = args.repo_id.strip().lower()
    try:
        repo_path = resolve_registered_repo_path(repo_id)
    except ValueError as exc:
        print(str(exc))
        return 1

    sources = stored_sources()
    source_name = args.source.strip().lower()
    if source_name not in sources:
        print(f"source not found: {source_name}")
        return 1
    source_record = sources[source_name]
    source_path = Path(source_record["path"]).expanduser().resolve()
    if not source_path.exists():
        print(f"source path not found: {source_path}")
        return 1

    package_id = args.package.strip().lower()
    version = args.version
    profile_id = args.profile
    install_root = args.install_root or f"payloads/{package_id}/{version}"
    description = args.description or f"imported from source {source_name}"
    try:
        manifest_path, artifact_root = import_local_source_package(
            repo_path,
            source_name,
            source_record,
            package_id=package_id,
            version=version,
            profile_id=profile_id,
            install_root=install_root,
            description=description,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    print(f"imported source into repo: {source_name}")
    print(f" - repo: {repo_id}")
    print(f" - repo path: {repo_path}")
    print(f" - package: {package_id}")
    print(f" - version: {version}")
    print(f" - profile: {profile_id}")
    print(f" - install root: {install_root}")
    print(f" - source path: {source_path}")
    print(f" - artifact root: {artifact_root}")
    print(f" - manifest: {manifest_path}")
    return 0


def effective_apt_context(args: argparse.Namespace) -> dict[str, str]:
    detected = detect_apt_context()
    return {
        "distro": args.distro or detected["distro"],
        "release": args.release or detected["release"],
        "arch": args.arch or detected["arch"],
    }


def cmd_apt_list(args: argparse.Namespace) -> int:
    if args.downloaded:
        packages = apt_snapshots_with_repo()
        if args.pattern:
            packages = [
                item
                for item in packages
                if args.pattern.lower() in item["package_name"].lower()
            ]
        if args.json:
            print_json({"packages": packages})
            return 0
        if not packages:
            print("no downloaded apt packages recorded in this repo")
            return 0
        print("downloaded apt package snapshots:")
        for package in packages:
            print(
                " - "
                f"{package['package_name']} {package['package_version']} "
                f"[repo={package['repo_id']}] "
                f"[{package['distro']} {package['release']} {package['arch']}] "
                f"[packages={package['package_count']}] "
                f"[deps={'yes' if package['with_deps'] else 'no'}]"
            )
            if args.verbose:
                print(f"   repo path: {package['repo_path']}")
                print(f"   artifact root: {package['artifact_root']}")
                print(f"   manifest: {package['manifest']}")
        return 0

    command = ["apt", "list"]
    if args.installed:
        command.append("--installed")
    command.append(args.pattern or "*")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr and not args.json:
        print(result.stderr.rstrip())
    return result.returncode


def cmd_apt_show(args: argparse.Namespace) -> int:
    if args.downloaded:
        manifest_path = None
        repo_id = ""
        repo_path = ""
        for registered in apt_snapshots_with_repo():
            if registered["package_name"] != args.package:
                continue
            if args.version is not None and registered["package_version"] != args.version:
                continue
            manifest_path = Path(str(registered["manifest"]))
            repo_id = str(registered["repo_id"])
            repo_path = str(registered["repo_path"])
            break
        if manifest_path is None:
            print(f"apt package snapshot not found: {args.package}")
            return 1
        data = load_json(manifest_path)
        if args.json:
            print_json(data)
            return 0
        context = data["context"]
        print(f"apt package snapshot: {data['package_name']}")
        print(f" - version: {data['package_version']}")
        print(f" - distro: {context['distro']}")
        print(f" - release: {context['release']}")
        print(f" - arch: {context['arch']}")
        print(f" - requested package: {data['requested_package']}")
        print(f" - include dependencies: {'yes' if data.get('with_deps') else 'no'}")
        print(f" - repo: {repo_id}")
        print(f" - repo path: {repo_path}")
        print(f" - artifact root: {data['artifact_root']}")
        print(f" - manifest: {manifest_path}")
        print(f" - downloaded packages: {len(data.get('packages', []))}")
        for package in data.get("packages", []):
            print(
                "   "
                f"{package['name']}={package['version']} "
                f"[file={package['filename']}]"
            )
        return 0

    version = args.version or apt_policy_version(args.package)
    metadata = apt_show_metadata(args.package, version)
    if args.json:
        print_json(
            {
                "package_name": args.package,
                "package_version": version,
                "metadata": metadata,
            }
        )
        return 0
    print(f"apt package: {args.package}")
    print(f" - version: {version}")
    for key in ["Package", "Version", "Architecture", "Depends", "Filename", "Description"]:
        if key in metadata:
            print(f" - {key.lower()}: {metadata[key]}")
    return 0


def cmd_apt_download(args: argparse.Namespace) -> int:
    root = primary_repo_path()
    context = effective_apt_context(args)
    requested_package = args.package
    requested_version = args.version or apt_policy_version(requested_package)
    package_names = [requested_package]
    if args.with_deps:
        package_names.extend(apt_dependency_names(requested_package))

    artifact_root = apt_artifact_root(
        root,
        context["distro"],
        context["release"],
        context["arch"],
        requested_package,
        requested_version,
    )
    pool_dir = artifact_root / "pool"
    metadata_dir = artifact_root / "metadata"
    pool_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    downloaded_packages: list[dict[str, object]] = []
    for package_name in package_names:
        version = requested_version if package_name == requested_package else apt_policy_version(package_name)
        deb_path = apt_download_package(pool_dir, package_name, version)
        downloaded_packages.append(
            {
                "name": package_name,
                "version": version,
                "filename": deb_path.name,
                "path": str(deb_path),
                "size": deb_path.stat().st_size,
            }
        )

    summary = {
        "schema_version": "1",
        "provider": "apt",
        "package_name": requested_package,
        "package_version": requested_version,
        "requested_package": requested_package,
        "with_deps": args.with_deps,
        "context": context,
        "downloaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "artifact_root": str(artifact_root),
        "packages": downloaded_packages,
        "apt_metadata": apt_show_metadata(requested_package, requested_version),
    }
    manifest_path = apt_package_manifest_path(root, requested_package, requested_version)
    dump_json(manifest_path, summary)
    dump_json(metadata_dir / "package.json", summary)

    print(f"downloaded apt package snapshot: {requested_package}")
    print(f" - version: {requested_version}")
    print(f" - distro: {context['distro']}")
    print(f" - release: {context['release']}")
    print(f" - arch: {context['arch']}")
    print(f" - include dependencies: {'yes' if args.with_deps else 'no'}")
    print(f" - repo path: {root}")
    print(f" - artifact root: {artifact_root}")
    print(f" - manifest: {manifest_path}")
    print(f" - package files: {len(downloaded_packages)}")
    return 0


def cmd_apt_import(args: argparse.Namespace) -> int:
    repo_id = args.repo_id.strip().lower()
    try:
        repo_path = resolve_registered_repo_path(repo_id)
    except ValueError as exc:
        print(str(exc))
        return 1
    provider_manifest_path = find_apt_package_manifest(repo_path, args.package, args.version)
    if provider_manifest_path is None:
        print(f"apt package snapshot not found in repo {repo_id}: {args.package}")
        print("hint: run `ofpm apt download <package>` first")
        return 1
    snapshot = load_json(provider_manifest_path)
    package_id = (args.package_id or args.package).strip().lower()
    version = snapshot["package_version"]
    manifest_path = repo_path / "catalog" / "packages" / package_id / version / "package.json"
    if manifest_path.exists():
        print(f"package manifest already exists: {manifest_path}")
        return 1
    description = args.description or snapshot.get("apt_metadata", {}).get("Description-en") or snapshot.get("apt_metadata", {}).get("Description") or f"apt snapshot for {args.package}"
    install_root = args.install_root or f"apt/{package_id}/{version}"
    package_manifest = build_apt_package_manifest(
        repo_path,
        provider_manifest_path,
        snapshot,
        package_id=package_id,
        profile_id=args.profile,
        install_root=install_root,
        description=description,
    )
    dump_json(manifest_path, package_manifest)
    print(f"imported apt snapshot into repo: {args.package}")
    print(f" - repo: {repo_id}")
    print(f" - repo path: {repo_path}")
    print(f" - package: {package_id}")
    print(f" - version: {version}")
    print(f" - profile: {args.profile}")
    print(f" - install root: {install_root}")
    print(f" - provider manifest: {provider_manifest_path}")
    print(f" - package manifest: {manifest_path}")
    return 0


def print_json(data: dict) -> None:
    import json

    print(json.dumps(data, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ofpm")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_root_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--root", choices=["system", "user"], default="user")
        command_parser.add_argument("--root-path")
        command_parser.add_argument("--all-roots", action="store_true")

    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(func=cmd_init)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("pattern", nargs="?")
    list_parser.add_argument("--installed", action="store_true")
    list_parser.add_argument("--all", action="store_true")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--verbose", action="store_true")
    add_root_options(list_parser)
    list_parser.set_defaults(func=cmd_list)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("package")
    show_parser.add_argument("--version")
    show_parser.add_argument("--files", action="store_true")
    show_parser.add_argument("--json", action="store_true")
    add_root_options(show_parser)
    show_parser.set_defaults(func=cmd_show)

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("package")
    install_parser.add_argument("--version")
    add_root_options(install_parser)
    install_parser.set_defaults(func=cmd_install)

    upgrade_parser = subparsers.add_parser("upgrade")
    upgrade_parser.add_argument("package")
    upgrade_parser.add_argument("--version")
    add_root_options(upgrade_parser)
    upgrade_parser.set_defaults(func=cmd_upgrade)

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("package")
    add_root_options(remove_parser)
    remove_parser.set_defaults(func=cmd_remove)

    verify_pkg_parser = subparsers.add_parser("verify")
    verify_pkg_parser.add_argument("package")
    verify_pkg_parser.add_argument("--target-root")
    verify_pkg_parser.add_argument("--strict-modes", action="store_true")
    add_root_options(verify_pkg_parser)
    verify_pkg_parser.set_defaults(func=cmd_verify)

    verify_source_parser = subparsers.add_parser("verify-source")
    verify_source_parser.add_argument("package")
    verify_source_parser.add_argument("--version")
    verify_source_parser.set_defaults(func=cmd_verify_source)

    state_parser = subparsers.add_parser("state")
    state_parser.add_argument("--json", action="store_true")
    add_root_options(state_parser)
    state_parser.set_defaults(func=cmd_state)

    env_parser = subparsers.add_parser("env")
    env_parser.add_argument("subject", nargs="?")
    env_parser.add_argument("package_name", nargs="?")
    env_parser.add_argument("--root", choices=["system", "user"], default="user")
    env_parser.add_argument("--root-path")
    env_parser.add_argument("--export", action="store_true")
    env_parser.add_argument("--format", choices=["bash", "modulefile"], default="bash")
    env_parser.set_defaults(func=cmd_env)

    install_cli_parser = subparsers.add_parser("install-cli")
    install_cli_parser.add_argument("output", nargs="?")
    install_cli_parser.add_argument("--python")
    install_cli_parser.add_argument("--source-root")
    install_cli_parser.add_argument("--force", action="store_true")
    install_cli_parser.set_defaults(func=cmd_install_cli)

    source_parser = subparsers.add_parser("source")
    source_subparsers = source_parser.add_subparsers(dest="source_command", required=True)

    source_list_parser = source_subparsers.add_parser("list")
    source_list_parser.add_argument("--json", action="store_true")
    source_list_parser.set_defaults(func=cmd_source_list)

    source_show_parser = source_subparsers.add_parser("show")
    source_show_parser.add_argument("source_name")
    source_show_parser.add_argument("--json", action="store_true")
    source_show_parser.set_defaults(func=cmd_source_show)

    source_add_parser = source_subparsers.add_parser("add")
    source_add_parser.add_argument("source_name")
    source_add_parser.add_argument("path")
    source_add_parser.set_defaults(func=cmd_source_add)

    source_remove_parser = source_subparsers.add_parser("remove")
    source_remove_parser.add_argument("source_name")
    source_remove_parser.set_defaults(func=cmd_source_remove)

    source_verify_parser = source_subparsers.add_parser("verify")
    source_verify_parser.add_argument("source_name")
    source_verify_parser.set_defaults(func=cmd_source_verify)

    repo_parser = subparsers.add_parser("repo")
    repo_subparsers = repo_parser.add_subparsers(dest="repo_command", required=True)

    repo_list_parser = repo_subparsers.add_parser("list")
    repo_list_parser.add_argument("--scope", choices=["user", "repo"], default="repo")
    repo_list_parser.add_argument("--json", action="store_true")
    repo_list_parser.set_defaults(func=cmd_repo_list)

    repo_add_parser = repo_subparsers.add_parser("add")
    repo_add_parser.add_argument("repo_id")
    repo_add_parser.add_argument("path")
    repo_add_parser.add_argument("--scope", choices=["user", "repo"], default="repo")
    repo_add_parser.set_defaults(func=cmd_repo_add)

    repo_remove_parser = repo_subparsers.add_parser("remove")
    repo_remove_parser.add_argument("repo_id")
    repo_remove_parser.add_argument("--scope", choices=["user", "repo"], default="repo")
    repo_remove_parser.set_defaults(func=cmd_repo_remove)

    repo_show_parser = repo_subparsers.add_parser("show")
    repo_show_parser.add_argument("repo_id")
    repo_show_parser.add_argument("--scope", choices=["user", "repo"], default="repo")
    repo_show_parser.set_defaults(func=cmd_repo_show)

    repo_import_parser = repo_subparsers.add_parser("import")
    repo_import_parser.add_argument("repo_id")
    repo_import_parser.add_argument("--source", required=True)
    repo_import_parser.add_argument("--package", required=True)
    repo_import_parser.add_argument("--version", default="1.0.0")
    repo_import_parser.add_argument("--profile", default="ubuntu-22.04")
    repo_import_parser.add_argument("--install-root")
    repo_import_parser.add_argument("--description")
    repo_import_parser.set_defaults(func=cmd_repo_import)

    apt_parser = subparsers.add_parser("apt")
    apt_subparsers = apt_parser.add_subparsers(dest="apt_command", required=True)

    apt_list_parser = apt_subparsers.add_parser("list")
    apt_list_parser.add_argument("pattern", nargs="?")
    apt_list_parser.add_argument("--installed", action="store_true")
    apt_list_parser.add_argument("--downloaded", action="store_true")
    apt_list_parser.add_argument("--json", action="store_true")
    apt_list_parser.add_argument("--verbose", action="store_true")
    apt_list_parser.set_defaults(func=cmd_apt_list)

    apt_show_parser = apt_subparsers.add_parser("show")
    apt_show_parser.add_argument("package")
    apt_show_parser.add_argument("--version")
    apt_show_parser.add_argument("--downloaded", action="store_true")
    apt_show_parser.add_argument("--json", action="store_true")
    apt_show_parser.set_defaults(func=cmd_apt_show)

    apt_download_parser = apt_subparsers.add_parser("download")
    apt_download_parser.add_argument("package")
    apt_download_parser.add_argument("--version")
    apt_download_parser.add_argument("--distro")
    apt_download_parser.add_argument("--release")
    apt_download_parser.add_argument("--arch")
    apt_download_parser.add_argument("--with-deps", action="store_true")
    apt_download_parser.set_defaults(func=cmd_apt_download)

    apt_import_parser = apt_subparsers.add_parser("import")
    apt_import_parser.add_argument("repo_id")
    apt_import_parser.add_argument("package")
    apt_import_parser.add_argument("--version")
    apt_import_parser.add_argument("--package-id")
    apt_import_parser.add_argument("--profile", default="ubuntu-22.04")
    apt_import_parser.add_argument("--install-root")
    apt_import_parser.add_argument("--description")
    apt_import_parser.set_defaults(func=cmd_apt_import)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
