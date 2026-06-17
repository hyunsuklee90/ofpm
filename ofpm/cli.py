from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ofpm.apt import (
    apt_repo_access_issue,
    apt_artifact_root,
    apt_source_line,
    build_apt_local_repo_from_root,
    apt_dependency_names,
    apt_download_package,
    apt_package_manifest_path,
    apt_policy_version,
    apt_show_metadata,
    detect_apt_context,
    find_apt_local_repo_roots,
    list_apt_local_repo_packages,
    list_apt_packages,
    safe_path_component,
)
from ofpm.package_def import dump_package_file, load_package_file
from ofpm.dnf import build_dnf_local_repo, dnf_repo_file_text, find_dnf_local_repo_roots, safe_path_component as dnf_safe_path_component
from ofpm.process_ui import run_command_live
from ofpm.core import (
    sync_managed_state_db,
    verify_state,
)
from ofpm.installers import (
    install_package_from_definition,
    remove_package_from_definition,
    verify_package_from_definition,
)
from ofpm.local_package import (
    import_local_package,
    scaffold_managed_files_package,
    test_local_package,
    verify_local_package,
)
from ofpm.modules import render_package_modulefile, render_package_shell_env
from ofpm.plugins import attach_plugin, detach_plugin, list_attached_plugins, refresh_plugins
from ofpm.prepare import get_preparer, list_preparers, prepare_package
from ofpm.repo_data import (
    find_installed_state,
    installed_states,
    list_available_packages,
    load_artifact_roots,
    load_json,
    managed_state_root,
    package_summary_from_manifest,
    native_repo_package_root,
    repo_repos_config_path,
    registered_repos,
    save_repos_config,
    verify_package_sources,
)
from ofpm.runtime_support import remove_managed_payload, verify_managed_files_install
from ofpm.state_db import (
    list_ownership_entries,
    list_receipts,
    managed_history_path,
    managed_ownership_root,
    managed_receipts_root,
)


class FriendlyArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(f"{self.prog}: unable to parse command", file=sys.stderr)
        invalid_choice = re.search(r"invalid choice: '([^']+)' \(choose from (.+)\)", message)
        if invalid_choice:
            choices = invalid_choice.group(2).replace("'", "").replace(", ", ", ")
            print(f" - unknown command or value: {invalid_choice.group(1)}", file=sys.stderr)
            print(f" - available choices: {choices}", file=sys.stderr)
        elif message.startswith("the following arguments are required:"):
            required = message.split(":", 1)[1].strip()
            print(f" - missing required argument: {required}", file=sys.stderr)
        elif message.startswith("unrecognized arguments:"):
            arguments = message.split(":", 1)[1].strip()
            print(f" - unrecognized argument: {arguments}", file=sys.stderr)
        else:
            print(f" - {message}", file=sys.stderr)
        print(f" - help: {self.prog} -h", file=sys.stderr)
        self.exit(2)


def repo_root() -> Path:
    configured = os.environ.get("OFPM_SOURCE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def is_ofpm_source_root(path: Path) -> bool:
    return (path / "ofpm" / "__main__.py").is_file() and (path / "ofpm" / "cli.py").is_file()


def install_source_root(explicit_source_root: str | None = None) -> Path:
    if explicit_source_root:
        return Path(explicit_source_root).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if is_ofpm_source_root(cwd):
        return cwd
    return repo_root()


def managed_source_root(root_kind: str) -> Path:
    return managed_root(root_kind) / "src"


def install_home_root(root_kind: str, launcher_path: Path) -> Path:
    if launcher_path.parent.name == "bin":
        return launcher_path.parent.parent
    return managed_root(root_kind)


def selected_repos_config_path(args: argparse.Namespace | None = None, root: Path | None = None) -> Path:
    raw = getattr(args, "repos_config", None) if args is not None else None
    if raw:
        return Path(raw).expanduser().resolve()
    return repo_repos_config_path(root or repo_root())


def configured_repos(args: argparse.Namespace | None = None, root: Path | None = None) -> dict[str, str]:
    base = root or repo_root()
    config_path = selected_repos_config_path(args, base)
    return registered_repos(base, config_path)


def selected_repo_entries(
    args: argparse.Namespace | None = None,
    root: Path | None = None,
) -> list[tuple[str, Path]]:
    direct_path = getattr(args, "repo_path", None) if args is not None else None
    if direct_path:
        return [("<direct>", Path(direct_path).expanduser().resolve())]

    repos = configured_repos(args, root)
    selected_repo = getattr(args, "repo", None) if args is not None else None
    if selected_repo:
        repo_id = selected_repo.strip().lower()
        if repo_id not in repos:
            config_path = selected_repos_config_path(args, root)
            raise ValueError(f"repo not found in {config_path}: {repo_id}")
        return [(repo_id, Path(repos[repo_id]).expanduser().resolve())]

    return [
        (repo_id, Path(repo_path).expanduser().resolve())
        for repo_id, repo_path in sorted(repos.items())
    ]


def primary_repo_path(args: argparse.Namespace | None = None, root: Path | None = None) -> Path:
    entries = selected_repo_entries(args, root)
    if entries:
        if len(entries) == 1:
            return entries[0][1]

        direct_selection = getattr(args, "repo", None) if args is not None else None
        if direct_selection:
            return entries[0][1]

        repos = dict(entries)
        preferred = repos.get("main")
        if preferred is not None:
            return preferred
        config_path = selected_repos_config_path(args, root)
        raise ValueError(
            f"multiple repos are registered in {config_path}; "
            "use `--repo <name>` or `--repo-path <path>`"
        )

    config_path = selected_repos_config_path(args, root)
    raise ValueError(f"no registered repos in {config_path}; use `ofpm repo add <name> <path>` first")


def managed_root(root_kind: str) -> Path:
    if root_kind == "system":
        return Path("/opt/ofpm")
    if root_kind == "user":
        home = Path(os.environ.get("HOME", "~")).expanduser()
        return home / ".ofpm"
    raise ValueError(f"unsupported root kind: {root_kind}")


def default_root_kind() -> str:
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() == 0:
        return "system"
    return "user"


def effective_root_kind(args: argparse.Namespace) -> str:
    root_kind = getattr(args, "root", None)
    if root_kind:
        return root_kind
    return default_root_kind()


def effective_managed_root(args: argparse.Namespace) -> Path:
    if getattr(args, "root_path", None):
        return Path(args.root_path).resolve()
    return managed_root(effective_root_kind(args))


def managed_roots_for_query(args: argparse.Namespace) -> list[tuple[str, Path]]:
    if getattr(args, "all_roots", False):
        return [("user", managed_root("user")), ("system", managed_root("system"))]
    if getattr(args, "root_path", None):
        return [(effective_root_kind(args), Path(args.root_path).resolve())]
    root_kind = effective_root_kind(args)
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


def equivalent_package_ids(package_id: str) -> list[str]:
    normalized = package_id.strip().lower()
    aliases = {
        "node": ["node-runtime"],
        "node-runtime": ["node"],
        "ollama": ["ollama-runtime"],
        "ollama-runtime": ["ollama"],
    }
    return [normalized, *aliases.get(normalized, [])]


def resolve_installed_state_for_action(args: argparse.Namespace, package_id: str) -> tuple[Path, dict[str, Any]] | None:
    allowed_ids = set(equivalent_package_ids(package_id))
    matches = [item for item in installed_states_for_query(args) if item["package_id"] in allowed_ids]
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
    allowed_ids = set(equivalent_package_ids(package_id))
    for root_kind in ["user", "system"]:
        for current_id in allowed_ids:
            if find_installed_state(managed_state_root(managed_root(root_kind)), current_id) is not None:
                return True
    return False


def effective_artifact_roots() -> dict[str, str]:
    return load_artifact_roots(repo_root())


def launcher_script_text(
    *,
    python_executable: str,
    source_root: Path,
    mode: str = "dev",
    ofpm_home: Path | None = None,
) -> str:
    quoted_python = python_executable.replace('"', '\\"')
    quoted_root = str(source_root).replace('"', '\\"')
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f'export OFPM_MODE="{mode}"',
        f'export OFPM_SOURCE_ROOT="{quoted_root}"',
        f'export PYTHONPATH="{quoted_root}${{PYTHONPATH:+:$PYTHONPATH}}"',
    ]
    if ofpm_home is not None:
        quoted_home = str(ofpm_home).replace('"', '\\"')
        lines.append(f'export OFPM_HOME="{quoted_home}"')
    lines.extend(
        [
            f'exec "{quoted_python}" -m ofpm "$@"',
            "",
        ]
    )
    return "\n".join(lines)


def default_ofpm_launcher_path(root_kind: str) -> Path:
    return managed_root(root_kind) / "bin" / "ofpm"


def default_ofpm_profile_path(root_kind: str) -> Path | None:
    if root_kind == "system":
        return Path("/etc/profile.d/ofpm.sh")
    if root_kind == "user":
        return Path(os.environ.get("HOME", "~")).expanduser() / ".bashrc"
    return None


def default_ofpm_system_bashrc_path() -> Path | None:
    candidates = [
        Path("/etc/bash.bashrc"),
        Path("/etc/bashrc"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def default_ofpm_symlink_path(root_kind: str) -> Path | None:
    return None


def ofpm_profile_script_text(*, root_kind: str, launcher_path: Path) -> str:
    managed = install_home_root(root_kind, launcher_path)
    launcher_dir = launcher_path.parent
    return "\n".join(
        [
            "# generated by ofpm install-ofpm",
            f'export OFPM_ROOT="{managed}"',
            f'if [ -d "{launcher_dir}" ] && [[ ":$PATH:" != *":{launcher_dir}:"* ]]; then',
            f'    export PATH="{launcher_dir}:$PATH"',
            "fi",
            "",
        ]
    )


def ofpm_bashrc_block_text(*, root_kind: str, launcher_path: Path) -> str:
    body = ofpm_profile_script_text(root_kind=root_kind, launcher_path=launcher_path).rstrip()
    return "\n".join(
        [
            "# >>> ofpm >>>",
            body,
            "# <<< ofpm <<<",
            "",
        ]
    )


def ofpm_system_bashrc_block_text(*, profile_path: Path) -> str:
    return "\n".join(
        [
            "# >>> ofpm >>>",
            f'[ -r "{profile_path}" ] && source "{profile_path}"',
            "# <<< ofpm <<<",
            "",
        ]
    )


def _write_text_file(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and path.is_dir():
        raise ValueError(f"path is a directory: {path}")
    if path.exists() and not force:
        raise FileExistsError(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bashrc_block(path: Path, content: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start_marker = "# >>> ofpm >>>"
    end_marker = "# <<< ofpm <<<"
    if start_marker in existing and end_marker in existing:
        prefix, remainder = existing.split(start_marker, 1)
        _current, suffix = remainder.split(end_marker, 1)
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        updated = prefix + content + suffix.lstrip("\n")
    else:
        updated = existing
        if updated and not updated.endswith("\n"):
            updated += "\n"
        updated += content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")


def _write_symlink(path: Path, target: Path, *, force: bool) -> None:
    if path.exists() or path.is_symlink():
        if not force:
            raise FileExistsError(str(path))
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def _copy_installed_repos(source_root: Path, install_home: Path, *, force: bool) -> None:
    source_repos = source_root / "repos"
    target_repos = install_home / "repos"
    if target_repos.exists():
        if not force:
            raise FileExistsError(str(target_repos))
        shutil.rmtree(target_repos)
    target_repos.mkdir(parents=True, exist_ok=True)

    included_repos = {
        Path("ofpm/main"),
        Path("ofpm/local-main"),
    }

    def ignore_copy(_directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if name in {"__pycache__", ".pytest_cache"}:
                ignored.add(name)
                continue
            if name.endswith(".pyc") or name.endswith(".pyo"):
                ignored.add(name)
        return ignored

    if not source_repos.exists():
        return
    for repo_relpath in sorted(included_repos, key=lambda item: item.as_posix()):
        source_repo = source_repos / repo_relpath
        if not source_repo.exists():
            continue
        shutil.copytree(source_repo, target_repos / repo_relpath, ignore=ignore_copy)


def _install_ofpm_source_tree(source_root: Path, target_root: Path, *, force: bool) -> None:
    if source_root == target_root:
        return
    if target_root.exists():
        if not force:
            raise FileExistsError(str(target_root))
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    included_dirs = {
        "ofpm",
        "docs",
    }
    included_files = {
        "README.md",
    }

    def ignore_copy(_directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if name in {"__pycache__", ".pytest_cache"}:
                ignored.add(name)
                continue
            if name.endswith(".pyc") or name.endswith(".pyo"):
                ignored.add(name)
        return ignored

    for child in sorted(source_root.iterdir(), key=lambda item: item.name):
        destination = target_root / child.name
        if child.is_dir() and child.name in included_dirs:
            shutil.copytree(child, destination, ignore=ignore_copy)
            continue
        if child.is_file() and child.name in included_files:
            shutil.copy2(child, destination)


def default_installed_repos(managed_home: Path) -> dict[str, str]:
    return {
        "main": str((managed_home / "repos" / "ofpm" / "main").resolve()),
        "local-main": str((managed_home / "repos" / "ofpm" / "local-main").resolve()),
    }


def resolve_registered_repo_path(
    repo_id: str,
    args: argparse.Namespace | None = None,
    root: Path | None = None,
) -> Path:
    repos = configured_repos(args, root or repo_root())
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


def build_target_from_profile(profile_id: str) -> dict[str, str]:
    distro, _, release = profile_id.partition("-")
    return {
        "os": "linux",
        "distro": distro or "generic",
        "release": release or "",
        "arch": "amd64",
    }


def build_source_package_manifest(
    source_label: str,
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
        "source_name": source_label,
        "origin_path": str(source_path),
        "origin_relroot": relpath_posix(artifact_root, manifest_root),
    }
    if source_path.is_dir():
        source_relpath = relpath_posix(artifact_root, manifest_root)
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
        "target": build_target_from_profile(profile_id),
        "install_root": install_root,
        "depends": [],
        "plugins": [],
        "plugin_data": [],
        "metadata": metadata,
        "files": files,
    }


def build_archive_package_manifest(
    archive_label: str,
    archive_path: Path,
    artifact_root: Path,
    manifest_root: Path,
    *,
    package_id: str,
    version: str,
    profile_id: str,
    install_root: str,
    description: str,
) -> dict[str, Any]:
    copied_archive = artifact_root / archive_path.name
    source_relpath = relpath_posix(copied_archive, manifest_root)
    return {
        "schema_version": "1",
        "package_id": package_id,
        "version": version,
        "target": build_target_from_profile(profile_id),
        "install_root": install_root,
        "depends": [],
        "plugins": [],
        "plugin_data": [],
        "metadata": {
            "description": description,
            "source_kind": "repo-internal",
            "source_name": archive_label,
            "origin_path": str(archive_path),
            "origin_relroot": relpath_posix(artifact_root, manifest_root),
            "install_mode": "archive",
            "archive_name": archive_path.name,
        },
        "env": {},
        "files": [
            {
                "source": source_relpath,
                "target": archive_path.name,
            }
        ],
    }


def load_repo_import_meta(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    meta_path = Path(path).expanduser().resolve()
    if not meta_path.exists():
        raise ValueError(f"metadata path not found: {meta_path}")
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"repo import metadata must be a JSON object: {meta_path}")
    return data


def repo_import_settings(
    args: argparse.Namespace,
    *,
    source_path: Path,
) -> tuple[str, str, str, str, str]:
    meta = load_repo_import_meta(getattr(args, "meta", None))
    package_id = (args.package or meta.get("package") or meta.get("package_id") or "").strip().lower()
    if not package_id:
        raise ValueError("package id is required; use `--package` or provide it in --meta")
    version = str(args.version or meta.get("version") or "1.0.0")
    profile_id = str(args.profile or meta.get("profile") or meta.get("profile_id") or "ubuntu-22.04")
    install_root = str(args.install_root or meta.get("install_root") or f"payloads/{package_id}/{version}")
    description = str(
        args.description
        or meta.get("description")
        or f"imported from source path {source_path.name}"
    )
    return package_id, version, profile_id, install_root, description


def import_local_source_package(
    repo_path: Path,
    source_path: Path,
    *,
    package_id: str,
    version: str,
    profile_id: str,
    install_root: str,
    description: str,
) -> tuple[Path, Path]:
    source_path = source_path.expanduser().resolve()
    source_kind = detect_source_kind(source_path)
    source_label = source_path.name
    manifest_root = native_repo_package_root(repo_path) / package_id / version
    manifest_path = manifest_root / "package.py"
    artifact_root = manifest_root / "payload"
    if manifest_path.exists():
        raise ValueError(f"package manifest already exists: {manifest_path}")
    if artifact_root.exists():
        raise ValueError(f"package payload root already exists: {artifact_root}")

    if source_kind == "dir":
        shutil.copytree(source_path, artifact_root, dirs_exist_ok=False)
    else:
        artifact_root.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source_path, artifact_root / source_path.name)

    manifest = build_source_package_manifest(
        source_label,
        source_path,
        artifact_root,
        manifest_root,
        package_id=package_id,
        version=version,
        profile_id=profile_id,
        install_root=install_root,
        description=description,
    )
    dump_package_file(manifest_path, manifest)
    return manifest_path, artifact_root


def import_local_archive_package(
    repo_path: Path,
    archive_path: Path,
    *,
    package_id: str,
    version: str,
    profile_id: str,
    install_root: str,
    description: str,
) -> tuple[Path, Path]:
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.is_file():
        raise ValueError(f"archive path not found: {archive_path}")
    manifest_root = native_repo_package_root(repo_path) / package_id / version
    manifest_path = manifest_root / "package.py"
    artifact_root = manifest_root / "payload"
    if manifest_path.exists():
        raise ValueError(f"package manifest already exists: {manifest_path}")
    if artifact_root.exists():
        raise ValueError(f"package payload root already exists: {artifact_root}")
    artifact_root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(archive_path, artifact_root / archive_path.name)
    manifest = build_archive_package_manifest(
        archive_path.name,
        archive_path,
        artifact_root,
        manifest_root,
        package_id=package_id,
        version=version,
        profile_id=profile_id,
        install_root=install_root,
        description=description,
    )
    dump_package_file(manifest_path, manifest)
    return manifest_path, artifact_root


def available_packages_with_repo(args: argparse.Namespace | None = None) -> list[dict[str, object]]:
    root = repo_root()
    artifact_roots = effective_artifact_roots()
    packages: list[dict[str, object]] = []
    for repo_id, repo_path in selected_repo_entries(args, root):
        package_base = native_repo_package_root(repo_path)
        if not package_base.exists():
            continue
        for item in list_available_packages(package_base, artifact_roots):
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


def package_manifests_with_repo(args: argparse.Namespace | None = None) -> list[dict[str, str]]:
    root = repo_root()
    manifests: list[dict[str, str]] = []
    for repo_id, repo_path in selected_repo_entries(args, root):
        package_root = native_repo_package_root(repo_path)
        candidates = sorted(package_root.glob("*/*/package.py"))
        if not candidates:
            candidates = sorted(package_root.glob("*/*/package.json"))
        for manifest_path in candidates:
            manifests.append(
                {
                    "repo_id": repo_id,
                    "repo_path": str(repo_path),
                    "manifest": str(manifest_path),
                }
            )
    return manifests


def find_registered_package_matches(
    args: argparse.Namespace | None,
    package_id: str,
    version: str | None = None,
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    allowed_ids = set(equivalent_package_ids(package_id))
    for entry in package_manifests_with_repo(args):
        manifest_path = Path(entry["manifest"])
        data = load_package_file(manifest_path)
        if data["package_id"] not in allowed_ids:
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
    return sorted(matches, key=lambda item: (item["repo_id"], item["version"]))


def find_registered_package_manifest(
    args: argparse.Namespace | None,
    package_id: str,
    version: str | None = None,
) -> dict[str, str] | None:
    matches = find_registered_package_matches(args, package_id, version)
    if not matches:
        return None

    repo_ids = sorted({item["repo_id"] for item in matches})
    if len(repo_ids) > 1:
        rendered = ", ".join(repo_ids)
        raise ValueError(
            f"package is available from multiple repos: {package_id} "
            f"(repos: {rendered}); use `--repo <name>` or `--repo-path <path>`"
        )
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
        manifest_entry = find_registered_package_manifest(None, package_id, version)
        if manifest_entry is None:
            raise ValueError(f"package not found: {spec}")
        resolved.append((spec, manifest_entry))
    return resolved


def apt_snapshots_with_repo(args: argparse.Namespace | None = None) -> list[dict[str, object]]:
    root = repo_root()
    snapshots: list[dict[str, object]] = []
    for repo_id, repo_path in selected_repo_entries(args, root):
        for provider_repo_path in apt_provider_snapshot_roots(repo_path):
            for item in list_apt_packages(provider_repo_path):
                snapshot = dict(item)
                snapshot["repo_id"] = repo_id
                snapshot["repo_path"] = str(provider_repo_path)
                snapshots.append(snapshot)
    return sorted(
        snapshots,
        key=lambda item: (
            str(item["package_name"]),
            str(item["package_version"]),
            str(item["repo_id"]),
        ),
    )


def apt_provider_snapshot_roots(repo_path: Path) -> list[Path]:
    candidates = [repo_path]
    if repo_path.parent.name == "ofpm":
        candidates.append(repo_path.parent.parent / "apt" / repo_path.name)
    if repo_path.parent.name == "main" and repo_path.parent.parent.name == "ofpm":
        candidates.append(repo_path.parent.parent.parent / "apt" / repo_path.parent.name)
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def find_apt_snapshot_matches(
    args: argparse.Namespace | None,
    package_name: str,
    version: str | None = None,
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for item in apt_snapshots_with_repo(args):
        if str(item["package_name"]) != package_name:
            continue
        if version is not None and str(item["package_version"]) != version:
            continue
        matches.append(item)
    return sorted(matches, key=lambda item: (str(item["repo_id"]), str(item["package_version"])))


def find_apt_snapshot(
    args: argparse.Namespace | None,
    package_name: str,
    version: str | None = None,
) -> dict[str, object] | None:
    matches = find_apt_snapshot_matches(args, package_name, version)
    if not matches:
        return None

    repo_ids = sorted({str(item["repo_id"]) for item in matches})
    if len(repo_ids) > 1:
        rendered = ", ".join(repo_ids)
        raise ValueError(
            f"apt package snapshot is available from multiple repos: {package_name} "
            f"(repos: {rendered}); use `--repo <name>` or `--repo-path <path>`"
        )
    return sorted(matches, key=lambda item: str(item["package_version"]))[-1]


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
        "repos/ofpm/main",
        "repos/apt/main",
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

    try:
        available = available_packages_with_repo(args)
    except ValueError as exc:
        print(str(exc))
        return 1
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
    try:
        matches = find_registered_package_matches(args, args.package, args.version)
    except ValueError as exc:
        print(str(exc))
        return 1
    if not matches:
        print(f"package not found: {args.package}")
        return 1
    if len({entry["repo_id"] for entry in matches}) > 1 and not getattr(args, "repo", None) and not getattr(args, "repo_path", None):
        if args.json:
            packages = [
                package_summary_from_manifest(
                    Path(entry["manifest"]),
                    include_files=args.files,
                    artifact_roots=artifact_roots,
                )
                | {"repo_id": entry["repo_id"], "repo_path": entry["repo_path"]}
                for entry in matches
            ]
            print_json({"packages": packages})
            return 0
        print(f"matching packages for: {args.package}")
        for entry in matches:
            manifest_path = Path(entry["manifest"])
            package = package_summary_from_manifest(
                manifest_path,
                include_files=False,
                artifact_roots=artifact_roots,
            )
            print(
                " - "
                f"{package['package_id']} {package['version']} "
                f"[repo={entry['repo_id']}] "
                f"[profile={package['profile_id']}] "
                f"[available={'yes' if package['available'] else 'no'}]"
            )
            print(f"   manifest: {entry['manifest']}")
        print("use `--repo <name>` or `--repo-path <path>` for a single detailed package view")
        return 0

    manifest_entry = sorted(matches, key=lambda item: item["version"])[-1]
    manifest_path = Path(manifest_entry["manifest"])
    package = package_summary_from_manifest(manifest_path, include_files=args.files, artifact_roots=artifact_roots)
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
            line = f" - {dep['package_id']} {dep_version}"
            if dep.get("reason"):
                line += f" {dep['reason']}"
            print(line)
    if package.get("plugins"):
        print("plugins:")
        for plugin in package["plugins"]:
            plugin_version = plugin.get("version", "*")
            line = f" - {plugin['package_id']} {plugin_version}"
            if plugin.get("reason"):
                line += f" {plugin['reason']}"
            print(line)
    if package.get("plugin_data"):
        print("plugin data:")
        for item in package["plugin_data"]:
            selector = item.get("package_id_prefix") or item.get("package_id") or item.get("kind", "*")
            line = f" - {selector}"
            if item.get("reason"):
                line += f" {item['reason']}"
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
    try:
        manifest_entry = find_registered_package_manifest(args, args.package, args.version)
    except ValueError as exc:
        print(str(exc))
        return 1
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


def cmd_package_verify(args: argparse.Namespace) -> int:
    try:
        result = verify_local_package(args.path)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"verify package dir: {result['package_root']}")
    print(f" - package: {result['package_id']}")
    print(f" - version: {result['version']}")
    print(f" - manifest: {result['manifest']}")
    print(f" - install root: {result['install_root']}")
    print(f" - declared source paths: {result['declared_source_count']}")
    print(f" - expanded files: {result['expanded_file_count']}")
    if result["availability_error"]:
        print(f" - availability error: {result['availability_error']}")
    if result["missing_sources"]:
        print(f" - missing source paths: {len(result['missing_sources'])}")
        for path in result["missing_sources"][:20]:
            print(f"   {path}")
    if result["missing_files"]:
        print(f" - missing expanded files: {len(result['missing_files'])}")
        for path in result["missing_files"][:20]:
            print(f"   {path}")
    if result["ok"]:
        print(" - result: verified")
        return 0
    print(" - result: failed")
    return 1


def cmd_package_test(args: argparse.Namespace) -> int:
    try:
        result = test_local_package(args.path, root_kind=effective_root_kind(args))
    except (FileExistsError, ValueError) as exc:
        print(str(exc))
        return 1
    print(f"test package dir: {Path(args.path).expanduser().resolve()}")
    print(f" - package: {result['package_id']}")
    print(f" - version: {result['version']}")
    print(f" - manifest: {result['manifest']}")
    print(f" - managed root: {result['managed_root']}")
    print(f" - current path: {result['current_path']}")
    print(f" - tracked files: {result['tracked_files']}")
    if result["verify_errors"]:
        print(" - verify result: failed")
        for error in result["verify_errors"]:
            print(f"   {error}")
        return 1
    print(" - verify result: verified")
    print(f" - remove result: {'removed' if result['removed'] else 'not-removed'}")
    print(" - result: passed")
    return 0


def cmd_package_init(args: argparse.Namespace) -> int:
    try:
        package_root = scaffold_managed_files_package(
            args.path,
            package_id=args.package_id,
            version=args.version,
            profile_id=args.profile,
            install_root=args.install_root,
            description=args.description or "",
            force=args.force,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"initialized package dir: {package_root}")
    print(f" - package: {args.package_id}")
    print(f" - version: {args.version}")
    print(f" - manifest: {package_root / 'package.py'}")
    print(f" - payload root: {package_root / 'payload'}")
    return 0


def resolve_prepare_repo_dir(args: argparse.Namespace) -> Path | None:
    if getattr(args, "repo_dir", None):
        return Path(args.repo_dir).expanduser().resolve()
    if getattr(args, "repo", None):
        return resolve_registered_repo_path(args.repo.strip().lower(), args)
    return None


def cmd_prepare_list(args: argparse.Namespace) -> int:
    rows = list_preparers()
    if getattr(args, "json", False):
        print(
            json.dumps(
                [
                    {
                        "id": item.id,
                        "source": item.source,
                        "output_package": item.output_package,
                        "description": item.description,
                    }
                    for item in rows
                ],
                indent=2,
            )
        )
        return 0
    print(f"{'ID':<10} {'Source':<10} {'Output package':<18} Description")
    for item in rows:
        print(f"{item.id:<10} {item.source:<10} {item.output_package:<18} {item.description}")
    return 0


def cmd_prepare_versions(args: argparse.Namespace) -> int:
    try:
        preparer = get_preparer(args.preparer_id)
        versions = preparer.list_versions()
    except (OSError, ValueError) as exc:
        print(str(exc))
        return 1
    if getattr(args, "json", False):
        print(json.dumps(versions, indent=2))
        return 0
    for version in versions:
        print(version)
    return 0


def cmd_prepare_run(args: argparse.Namespace) -> int:
    try:
        repo_dir = resolve_prepare_repo_dir(args)
    except ValueError as exc:
        print(str(exc))
        return 1
    work_dir = Path(args.work_dir).expanduser().resolve() if args.work_dir else None
    if repo_dir is None and work_dir is None:
        print("prepare needs an output target: use --repo <id>, --repo-dir <path>, or --work-dir <path>")
        return 1
    try:
        prepared = prepare_package(
            args.preparer_id,
            args.version,
            repo_dir=repo_dir,
            work_dir=work_dir,
            replace=args.replace,
            progress=print,
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(str(exc))
        return 1
    print(f"prepared package: {prepared.package_id}")
    print(f" - version: {prepared.version}")
    print(f" - source: {prepared.source}")
    if prepared.sha256:
        print(f" - sha256: {prepared.sha256}")
    if prepared.package_root.exists():
        print(f" - package root: {prepared.package_root}")
    if prepared.repo_package_root is not None:
        print(f" - repo package root: {prepared.repo_package_root}")
    return 0


def cmd_prepare_item(args: argparse.Namespace) -> int:
    if args.action == "list":
        return cmd_prepare_versions(args)
    args.version = args.action
    return cmd_prepare_run(args)


def cmd_repo_import_package(args: argparse.Namespace) -> int:
    repo_id = args.repo_id.strip().lower()
    try:
        repo_path = resolve_registered_repo_path(repo_id, args)
        check = verify_local_package(args.path)
    except ValueError as exc:
        print(str(exc))
        return 1
    if not check["ok"]:
        print(f"package verification failed: {args.path}")
        print("run `ofpm package verify <path>` and fix the package before import")
        return 1
    try:
        package, dest_root = import_local_package(
            repo_path,
            args.path,
            replace=args.replace,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"imported package dir into repo: {package.package_data['package_id']}")
    print(f" - repo: {repo_id}")
    print(f" - repo path: {repo_path}")
    print(f" - package root: {package.package_root}")
    print(f" - package: {package.package_data['package_id']}")
    print(f" - version: {package.package_data['version']}")
    print(f" - manifest: {dest_root / package.manifest_path.name}")
    print(f" - payload root: {dest_root / 'payload'}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    require_offline_target_mode("install")
    artifact_roots = effective_artifact_roots()
    try:
        manifest_entry = find_registered_package_manifest(args, args.package, args.version)
    except ValueError as exc:
        print(str(exc))
        return 1
    if manifest_entry is None:
        print(f"package not found: {args.package}")
        return 1
    manifest_path = Path(manifest_entry["manifest"])
    package = package_summary_from_manifest(manifest_path, artifact_roots=artifact_roots)
    managed = effective_managed_root(args)
    package_data = load_package_file(manifest_path)
    print(f"install plan for {package['package_id']} {package['version']}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    print(f" - managed root: {managed}")
    print(f" - check catalog manifest: {package['manifest']}")
    print(f" - check target profile compatibility: expected {package['profile_id']}")
    print(f" - install root policy: {package['install_root']}")
    print(f" - package file count: {package['file_count']}")
    try:
        state = install_package_from_definition(
            managed,
            manifest_path,
            package_data,
            root_kind=effective_root_kind(args),
            artifact_roots=artifact_roots,
        )
    except FileExistsError as exc:
        installed = find_installed_state(managed_state_root(managed), package["package_id"])
        print(f"install failed: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        if installed and installed["package_version"] == package["version"]:
            print(" - reason: package version is already installed")
            print(f" - installed state: {installed['state_path']}")
            print(f" - current version root: {installed['raw']['package'].get('version_root', '<unknown>')}")
            print(" - next action: use `ofpm verify <package>` or `ofpm remove <package>`")
            return 1
        print(" - reason: install path already exists but installed state does not match")
        print(f" - conflicting path: {exc}")
        print(" - next action: inspect `ofpm state` and remove stale files before retrying")
        return 1
    print(f"installed package: {package['package_id']} {package['version']}")
    print(f" - managed root: {managed}")
    print(f" - current path: {state['package']['current_path']}")
    if "library_dir" in state["package"]:
        print(f" - library dir: {state['package']['library_dir']}")
    if "install_mode" in state["package"]:
        print(f" - install mode: {state['package']['install_mode']}")
    for artifact in state["package"].get("artifacts", []):
        if "source" in artifact:
            print(f" - archive source: {artifact['source']}")
        if "stored_path" in artifact:
            print(f" - stored archive: {artifact['stored_path']}")
        if "size" in artifact:
            print(f" - archive size: {artifact['size']} bytes ({format_bytes(int(artifact['size']))})")
    if "config_dir" in state["package"]:
        print(f" - config dir: {state['package']['config_dir']}")
    if "models_path" in state["package"]:
        print(f" - models path: {state['package']['models_path']}")
    if "tracked_files" in state["package"]:
        print(f" - tracked files: {len(state['package']['tracked_files'])}")
    print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
    return 0


def remove_installed_package(
    managed: Path,
    installed: dict[str, Any],
    args: argparse.Namespace | None = None,
) -> dict[str, Any] | None:
    manifest_entry = find_registered_package_manifest(args, installed["package_id"], installed["package_version"])
    if manifest_entry is not None:
        manifest_path = Path(manifest_entry["manifest"])
        package_data = load_package_file(manifest_path)
        result = remove_package_from_definition(
            managed,
            manifest_path,
            package_data,
            installed,
            root_kind=installed.get("selected_root_kind", "user"),
        )
        if result is not None:
            return result
    if installed["raw"].get("install_type") == "managed-install" and installed["raw"]["package"].get("version_root"):
        return remove_managed_payload(managed, installed)
    return None


def cleanup_stale_install_paths(managed: Path, package_data: dict[str, Any]) -> list[Path]:
    removed: list[Path] = []
    package_id = str(package_data["package_id"])
    version = str(package_data["version"])
    install_roots = {
        managed / "payloads" / package_id / version,
    }
    if package_id == "node":
        install_roots.add(managed / "payloads" / "node-runtime" / version)
    if package_id == "ollama":
        install_roots.add(managed / "payloads" / "ollama-runtime" / version)

    for version_root in sorted(install_roots):
        if version_root.exists():
            shutil.rmtree(version_root)
            removed.append(version_root)
        current_link = version_root.parent / "current"
        if current_link.is_symlink() or current_link.exists():
            current_target = current_link.resolve() if current_link.is_symlink() else None
            if current_target is None or current_target == version_root:
                current_link.unlink()
    return removed


def cmd_reinstall(args: argparse.Namespace) -> int:
    require_offline_target_mode("reinstall")
    artifact_roots = effective_artifact_roots()
    try:
        manifest_entry = find_registered_package_manifest(args, args.package, args.version)
    except ValueError as exc:
        print(str(exc))
        return 1
    if manifest_entry is None:
        print(f"package not found: {args.package}")
        return 1

    manifest_path = Path(manifest_entry["manifest"])
    package = package_summary_from_manifest(manifest_path, artifact_roots=artifact_roots)
    package_data = load_package_file(manifest_path)

    resolved = resolve_installed_state_for_action(args, args.package)
    if resolved is not None:
        managed, installed = resolved
        print(f"reinstall plan for {package['package_id']} {package['version']}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - existing version: {installed['package_version']}")
        print(f" - existing state: {installed['state_path']}")
        print(" - action: remove existing install before fresh install")
        result = remove_installed_package(managed, installed, args)
        if result is not None:
            print(f"removed package: {result['package_id']} {result['package_version']}")
            print(f" - managed root: {result['managed_root']}")
            print(f" - removed version root: {result['removed_version_root']}")
        else:
            print(f"reinstall failed: could not remove installed package {args.package}")
            return 1
    else:
        if any_installed_state(args.package):
            return 1
        managed = effective_managed_root(args)
        print(f"reinstall plan for {package['package_id']} {package['version']}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(" - existing version: not installed")
        print(" - action: install only")
        removed_stale = cleanup_stale_install_paths(managed, package_data)
        if removed_stale:
            print(f" - stale path cleanup: removed {len(removed_stale)} path(s)")
            for path in removed_stale:
                print(f"   {path}")

    print(f" - check catalog manifest: {package['manifest']}")
    print(f" - check target profile compatibility: expected {package['profile_id']}")
    print(f" - install root policy: {package['install_root']}")
    print(f" - package file count: {package['file_count']}")
    try:
        state = install_package_from_definition(
            managed,
            manifest_path,
            package_data,
            root_kind=effective_root_kind(args),
            artifact_roots=artifact_roots,
        )
    except FileExistsError as exc:
        print(f"reinstall failed: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(" - reason: install path still exists after reinstall preparation")
        print(f" - conflicting path: {exc}")
        return 1

    print(f"reinstalled package: {package['package_id']} {package['version']}")
    print(f" - managed root: {managed}")
    print(f" - current path: {state['package']['current_path']}")
    if "tracked_files" in state["package"]:
        print(f" - tracked files: {len(state['package']['tracked_files'])}")
    print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    require_offline_target_mode("upgrade")
    resolved = resolve_installed_state_for_action(args, args.package)
    installed = resolved[1] if resolved is not None else None
    try:
        manifest_entry = find_registered_package_manifest(args, args.package, args.version)
    except ValueError as exc:
        print(str(exc))
        return 1
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
    result = remove_installed_package(managed, installed, args)
    if result is not None:
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
    try:
        manifest_entry = find_registered_package_manifest(args, installed["package_id"], installed["package_version"])
    except ValueError as exc:
        print(str(exc))
        return 1
    if manifest_entry is not None:
        manifest_path = Path(manifest_entry["manifest"])
        package_data = load_package_file(manifest_path)
        errors = verify_package_from_definition(
            managed,
            manifest_path,
            package_data,
            installed,
            root_kind=installed.get("selected_root_kind", "user"),
            strict_modes=args.strict_modes,
            target_root=Path(args.target_root).resolve() if args.target_root else None,
        )
        if errors is not None:
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
            root / "payloads" / "node" / "current" / "bin",
            root / "payloads" / "node-runtime" / "current" / "bin",
            root / "payloads" / "pi-agent" / "current" / "bin",
            root / "payloads" / "ollama" / "current" / "bin",
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

    root_kind = effective_root_kind(args)
    print(f"root kind: {root_kind}")
    print(f"managed root: {root}")
    print("path entries:")
    for entry in path_entries:
        print(f" - {entry}")
    print("shell snippet:")
    for line in export_lines:
        print(f"  {line}")
    print("usage:")
    print(f" - one-shot: eval \"$(python3 -m ofpm env --root {root_kind} --export)\"")
    print(f" - inspect only: python3 -m ofpm env --root {root_kind}")
    print(f" - package bash: python3 -m ofpm env package <package> --root {root_kind}")
    print(f" - package modulefile: python3 -m ofpm env package <package> --root {root_kind} --format modulefile")
    print("notes:")
    print(" - this does not modify your shell automatically")
    print(" - edit the snippet before adding it to ~/.bashrc if you want a different PATH order")
    return 0


def cmd_plugin_list(args: argparse.Namespace) -> int:
    managed = effective_managed_root(args)
    attached = list_attached_plugins(managed, args.host_package)
    print(f"plugin host: {args.host_package}")
    print(f"managed root: {managed}")
    if not attached:
        print("attached plugin count: 0")
        return 0
    print(f"attached plugin count: {len(attached)}")
    for item in attached:
        print(f" - {item['package_id']} {item.get('package_version', '')}".rstrip())
    return 0


def cmd_plugin_attach(args: argparse.Namespace) -> int:
    managed = effective_managed_root(args)
    result = attach_plugin(managed, args.host_package, args.plugin_package)
    refresh_plugins(managed, args.host_package)
    print(f"attached plugin: {result['plugin_package_id']} {result['plugin_package_version']}")
    print(f" - host: {result['host_package_id']}")
    print(f" - managed root: {managed}")
    return 0


def cmd_plugin_detach(args: argparse.Namespace) -> int:
    managed = effective_managed_root(args)
    result = detach_plugin(managed, args.host_package, args.plugin_package)
    refresh_plugins(managed, args.host_package)
    print(f"detached plugin: {result['plugin_package_id']}")
    print(f" - host: {result['host_package_id']}")
    print(f" - removed: {'yes' if result['removed'] else 'no'}")
    print(f" - managed root: {managed}")
    return 0


def cmd_plugin_refresh(args: argparse.Namespace) -> int:
    managed = effective_managed_root(args)
    result = refresh_plugins(managed, args.host_package)
    print(f"refreshed plugins for managed root: {managed}")
    if args.host_package:
        print(f" - host: {args.host_package}")
    print(f" - refreshed host count: {len(result['refreshed_hosts'])}")
    for item in result["refreshed_hosts"]:
        print(f"   {item['package_id']} {item['package_version']}")
    for note in result["notes"]:
        print(f" - note: {note}")
    return 0


def cmd_install_cli(args: argparse.Namespace) -> int:
    root_kind = args.root or default_root_kind()
    raw_output = args.output
    output_path = Path(raw_output).expanduser().resolve() if raw_output else default_ofpm_launcher_path(root_kind)
    install_home = install_home_root(root_kind, output_path)
    python_executable = args.python or sys.executable
    source_root = install_source_root(args.source_root)
    installed_source_root = install_home / "src"
    installed_repo_root = install_home / "repos" / "ofpm" / "main"
    installed_repos_config = install_home / "config" / "repos.json"
    profile_path = Path(args.profile_path).expanduser().resolve() if args.profile_path else default_ofpm_profile_path(root_kind)
    bashrc_path = Path(args.bashrc_path).expanduser().resolve() if args.bashrc_path else (
        default_ofpm_system_bashrc_path() if root_kind == "system" else None
    )
    symlink_path = Path(args.symlink_path).expanduser().resolve() if args.symlink_path else default_ofpm_symlink_path(root_kind)

    content = launcher_script_text(
        python_executable=python_executable,
        source_root=installed_source_root,
        mode="installed",
        ofpm_home=install_home,
    )
    try:
        if output_path.exists() and output_path.is_dir():
            print(f"launcher path is a directory: {output_path}")
            print("choose a file path, for example: install-ofpm /opt/ofpm/bin/ofpm")
            return 1
        _install_ofpm_source_tree(source_root, installed_source_root, force=args.force)
        _copy_installed_repos(source_root, install_home, force=args.force)
        installed_repo_root.mkdir(parents=True, exist_ok=True)
        (install_home / "repos" / "ofpm" / "local-main").mkdir(parents=True, exist_ok=True)
        save_repos_config(installed_repos_config, default_installed_repos(install_home))
        _write_text_file(output_path, content, force=args.force)
        os.chmod(output_path, 0o755)

        if profile_path and not args.no_profile:
            if root_kind == "user" and profile_path.name == ".bashrc":
                _write_bashrc_block(
                    profile_path,
                    ofpm_bashrc_block_text(root_kind=root_kind, launcher_path=output_path),
                )
            else:
                _write_text_file(
                    profile_path,
                    ofpm_profile_script_text(root_kind=root_kind, launcher_path=output_path),
                    force=args.force,
                )

        if root_kind == "system" and bashrc_path and not args.no_profile:
            _write_bashrc_block(
                bashrc_path,
                ofpm_system_bashrc_block_text(profile_path=profile_path or Path("/etc/profile.d/ofpm.sh")),
            )

        if symlink_path and not args.no_symlink:
            _write_symlink(symlink_path, output_path, force=args.force)
    except FileExistsError as exc:
        print(f"path already exists: {exc}")
        print("use --force to overwrite it")
        return 1
    except PermissionError as exc:
        print(f"permission denied: {exc.filename}")
        print("hint: run with appropriate privileges or choose paths under a writable directory")
        return 1
    except ValueError as exc:
        print(str(exc))
        return 1

    print("installed ofpm launcher")
    print("closest existing model: this behaves more like `make install` than `apt install`")
    print(f" - root kind: {root_kind}")
    print(f" - output: {output_path}")
    print(f" - installed source root: {installed_source_root}")
    print(f" - installed repo root: {installed_repo_root}")
    print(f" - repo config: {installed_repos_config}")
    if profile_path and not args.no_profile:
        print(f" - shell hook: {profile_path}")
    else:
        print(" - shell hook: disabled")
    if root_kind == "system" and bashrc_path and not args.no_profile:
        print(f" - bashrc hook: {bashrc_path}")
    if symlink_path and not args.no_symlink:
        print(f" - command link: {symlink_path}")
    else:
        print(" - command link: disabled")
    print(f" - python: {python_executable}")
    print(f" - source root: {source_root}")
    print(f" - run: {symlink_path if symlink_path and not args.no_symlink else output_path} --help")
    return 0


def cmd_reinstall_cli(args: argparse.Namespace) -> int:
    reinstall_args = argparse.Namespace(**vars(args))
    reinstall_args.force = True
    return cmd_install_cli(reinstall_args)


def stored_repos(args: argparse.Namespace) -> dict[str, str]:
    path = selected_repos_config_path(args)
    if not path.exists():
        return {}
    return load_json(path)


def cmd_repo_list(args: argparse.Namespace) -> int:
    path = selected_repos_config_path(args)
    repos = stored_repos(args)
    if args.json:
        print_json({"config_path": str(path), "repos": repos})
        return 0
    if not repos:
        print(f"no registered repos in {path}")
        return 0
    print(f"config path: {path}")
    print("registered repos:")
    for repo_id, repo_path in sorted(repos.items()):
        print(f" - {repo_id}: {repo_path}")
    return 0


def cmd_repo_add(args: argparse.Namespace) -> int:
    path = selected_repos_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    repo_path = str(Path(args.path).expanduser().resolve())
    repos[repo_id] = repo_path
    save_repos_config(path, repos)
    print(f"registered repo: {repo_id}")
    print(f" - path: {repo_path}")
    print(f" - config: {path}")
    return 0


def cmd_repo_remove(args: argparse.Namespace) -> int:
    path = selected_repos_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    if repo_id not in repos:
        print(f"repo not found: {repo_id}")
        print(f" - config: {path}")
        return 1
    removed_path = repos.pop(repo_id)
    save_repos_config(path, repos)
    print(f"removed repo: {repo_id}")
    print(f" - path: {removed_path}")
    print(f" - config: {path}")
    return 0


def cmd_repo_show(args: argparse.Namespace) -> int:
    path = selected_repos_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    if repo_id not in repos:
        print(f"repo not found: {repo_id}")
        print(f" - config: {path}")
        return 1
    print(f"repo: {repo_id}")
    print(f" - path: {repos[repo_id]}")
    print(f" - config: {path}")
    return 0


def cmd_repo_import(args: argparse.Namespace) -> int:
    repo_id = args.repo_id.strip().lower()
    try:
        repo_path = resolve_registered_repo_path(repo_id, args)
    except ValueError as exc:
        print(str(exc))
        return 1

    source_path = Path(args.path).expanduser().resolve()
    if not source_path.exists():
        print(f"source path not found: {source_path}")
        return 1
    if not source_path.is_dir():
        print(f"repo import expects a directory payload: {source_path}")
        print("hint: use `ofpm repo import-archive ... --archive <path>` for tar.gz-style releases")
        return 1

    try:
        package_id, version, profile_id, install_root, description = repo_import_settings(
            args,
            source_path=source_path,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    try:
        manifest_path, artifact_root = import_local_source_package(
            repo_path,
            source_path,
            package_id=package_id,
            version=version,
            profile_id=profile_id,
            install_root=install_root,
            description=description,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    print(f"imported source into repo: {source_path.name}")
    print(f" - repo: {repo_id}")
    print(f" - repo path: {repo_path}")
    print(f" - package: {package_id}")
    print(f" - version: {version}")
    print(f" - profile: {profile_id}")
    print(f" - install root: {install_root}")
    print(f" - source path: {source_path}")
    print(f" - payload root: {artifact_root}")
    print(f" - manifest: {manifest_path}")
    return 0


def cmd_repo_import_archive(args: argparse.Namespace) -> int:
    repo_id = args.repo_id.strip().lower()
    try:
        repo_path = resolve_registered_repo_path(repo_id, args)
    except ValueError as exc:
        print(str(exc))
        return 1

    archive_path = Path(args.archive).expanduser().resolve()
    if not archive_path.exists():
        print(f"archive path not found: {archive_path}")
        return 1
    if not archive_path.is_file():
        print(f"repo import-archive expects a file archive: {archive_path}")
        return 1

    try:
        package_id, version, profile_id, install_root, description = repo_import_settings(
            args,
            source_path=archive_path,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    try:
        manifest_path, artifact_root = import_local_archive_package(
            repo_path,
            archive_path,
            package_id=package_id,
            version=version,
            profile_id=profile_id,
            install_root=install_root,
            description=description,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    print(f"imported archive into repo: {archive_path.name}")
    print(f" - repo: {repo_id}")
    print(f" - repo path: {repo_path}")
    print(f" - package: {package_id}")
    print(f" - version: {version}")
    print(f" - profile: {profile_id}")
    print(f" - install root: {install_root}")
    print(f" - archive path: {archive_path}")
    print(f" - payload root: {artifact_root}")
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
    base_path = Path(args.path).expanduser().resolve()
    recursive = bool(getattr(args, "recursive", False))
    repo_roots = find_apt_local_repo_roots(base_path) if recursive else [base_path]
    if not repo_roots or any(not ((repo_root / "Packages").exists() or (repo_root / "Packages.gz").exists()) for repo_root in repo_roots):
        print(f"apt local repo metadata not found: {base_path}")
        print("hint: run `ofpm apt build-repo <package>` in that directory first")
        print("hint: use `ofpm apt list <parent> --recursive` when a parent contains multiple apt repos")
        return 1

    packages: list[dict[str, object]] = []
    try:
        for repo_root in repo_roots:
            packages.extend(list_apt_local_repo_packages(repo_root))
    except ValueError as exc:
        print(str(exc))
        return 1

    pattern = getattr(args, "pattern", None)
    if pattern:
        packages = [
            item
            for item in packages
            if pattern.lower() in str(item["package_name"]).lower()
        ]
    if args.json:
        print_json({"packages": packages})
        return 0
    if not packages:
        print("no apt packages found in selected local repo metadata")
        return 0
    print("apt local repo packages:")
    print(f"repo root count: {len(repo_roots)}")
    print(f"package count: {len(packages)}")
    for package in packages:
        print(
            " - "
            f"{package['package_name']} {package['package_version']} "
            f"[arch={package['architecture']}] "
            f"[file={package['filename']}]"
        )
        if args.verbose:
            print(f"   repo root: {package['repo_root']}")
            if package.get("size"):
                print(f"   size: {package['size']}")
    return 0


def cmd_apt_show(args: argparse.Namespace) -> int:
    base_path = Path(args.path).expanduser().resolve()
    recursive = bool(getattr(args, "recursive", False))
    repo_roots = find_apt_local_repo_roots(base_path) if recursive else [base_path]
    if not repo_roots or any(not ((repo_root / "Packages").exists() or (repo_root / "Packages.gz").exists()) for repo_root in repo_roots):
        print(f"apt local repo metadata not found: {base_path}")
        print("hint: run `ofpm apt build-repo <package>` in that directory first")
        print("hint: use `ofpm apt show <package> <parent> --recursive` when a parent contains multiple apt repos")
        return 1

    packages: list[dict[str, object]] = []
    try:
        for repo_root in repo_roots:
            packages.extend(list_apt_local_repo_packages(repo_root))
    except ValueError as exc:
        print(str(exc))
        return 1
    matches = [
        item
        for item in packages
        if str(item["package_name"]) == args.package
        and (args.version is None or str(item["package_version"]) == args.version)
    ]
    if not matches:
        print(f"apt package not found in local repo metadata: {args.package}")
        return 1
    if len(matches) > 1 and not args.json:
        exact_roots = sorted({str(item["repo_root"]) for item in matches})
        if len(exact_roots) > 1:
            print(f"matching apt packages for: {args.package}")
            for item in matches:
                print(
                    " - "
                    f"{item['package_name']} {item['package_version']} "
                    f"[arch={item['architecture']}] "
                    f"[repo_root={item['repo_root']}]"
                )
            print("use a narrower path for a single detailed package view")
            return 0
    if args.json:
        print_json({"packages": matches})
        return 0
    selected = sorted(matches, key=lambda item: str(item["package_version"]))[-1]
    print(f"apt package: {selected['package_name']}")
    print(f" - version: {selected['package_version']}")
    print(f" - arch: {selected['architecture']}")
    print(f" - repo root: {selected['repo_root']}")
    print(f" - file: {selected['filename']}")
    if selected.get("size"):
        print(f" - size: {selected['size']}")
    if selected.get("description"):
        print(f" - description: {selected['description']}")
    return 0


def cmd_apt_commands(args: argparse.Namespace) -> int:
    package = args.package.strip()
    output_path = Path(args.output).expanduser().resolve() if args.output else Path.cwd().resolve()
    source_name = args.source_name or f"ofpm-{safe_path_component(package)}"

    print(f"apt helper for: {package}")
    print(f" - output: {output_path}")
    print(" - include dependencies: yes")
    print("builder-side:")
    build_cmd = f"ofpm apt build-repo {package}"
    if args.version:
        build_cmd += f" --version {args.version}"
    if args.output:
        build_cmd += f" --output {output_path}"
    print(f"   {build_cmd}")
    print("target-side:")
    activate_cmd = f"sudo ofpm apt activate {output_path} --source-name {source_name}"
    print(f"   {activate_cmd}")
    print(f"   dpkg -s {package} >/dev/null 2>&1 || sudo apt install {package}")
    print("optional cleanup:")
    print(f"   sudo apt remove {package}")
    print(f"   sudo ofpm apt deactivate {output_path} --source-name {source_name}")
    return 0


def cmd_apt_help(args: argparse.Namespace) -> int:
    parser = getattr(args, "_apt_parser", None)
    if parser is not None:
        print(parser.format_help().rstrip())
    print()
    print("common flow:")
    print("  mkdir -p ./zstd-repo")
    print("  cd ./zstd-repo")
    print("  ofpm apt build-repo zstd")
    print("  sudo ofpm apt activate .")
    print("  sudo apt install zstd")
    print("  sudo ofpm apt deactivate .")
    print()
    print("helper output:")
    print("  ofpm apt commands zstd")
    return 0


def cmd_apt_download(args: argparse.Namespace) -> int:
    try:
        root = primary_repo_path(args)
    except ValueError as exc:
        print(str(exc))
        return 1
    context = effective_apt_context(args)
    requested_package = args.package
    requested_version = args.version or apt_policy_version(requested_package)
    package_names = [requested_package]
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
        "with_deps": True,
        "context": context,
        "downloaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "artifact_root": str(artifact_root),
        "packages": downloaded_packages,
        "apt_metadata": apt_show_metadata(requested_package, requested_version),
    }
    manifest_path = apt_package_manifest_path(root, requested_package, requested_version)
    dump_package_file(manifest_path, summary)
    dump_package_file(metadata_dir / "package.py", summary)

    print(f"downloaded apt package snapshot: {requested_package}")
    print(f" - version: {requested_version}")
    print(f" - distro: {context['distro']}")
    print(f" - release: {context['release']}")
    print(f" - arch: {context['arch']}")
    print(" - include dependencies: yes")
    print(f" - repo path: {root}")
    print(f" - payload root: {artifact_root}")
    print(f" - manifest: {manifest_path}")
    print(f" - package files: {len(downloaded_packages)}")
    return 0


def isolated_apt_update(source_path: Path) -> None:
    run_command_live(
        [
            "apt-get",
            "-o",
            f"Dir::Etc::sourcelist={source_path}",
            "-o",
            "Dir::Etc::sourceparts=-",
            "-o",
            "APT::Get::List-Cleanup=0",
            "update",
        ],
        label="apt update",
    )


def apt_repo_source_name(base_path: Path, repo_root: Path, source_name: str | None = None) -> str:
    if source_name:
        prefix = source_name
    else:
        prefix = "ofpm"
    if repo_root.resolve() == base_path.resolve():
        suffix = safe_path_component(repo_root.name)
    else:
        suffix = safe_path_component(str(repo_root.resolve().relative_to(base_path.resolve())))
    return f"{prefix}-{suffix}"


def apt_source_file_path(
    repo_root: Path,
    base_path: Path,
    source_name: str | None,
    source_path: str | None,
    recursive: bool,
) -> Path:
    if source_path:
        configured = Path(source_path).expanduser().resolve()
        if recursive:
            return configured / f"{apt_repo_source_name(base_path, repo_root, source_name)}.list"
        return configured
    source_name_value = apt_repo_source_name(base_path, repo_root, source_name)
    return Path(f"/etc/apt/sources.list.d/{source_name_value}.list").resolve()


def dnf_repo_id_for_root(base_path: Path, repo_root: Path, repo_id: str | None = None) -> str:
    if repo_id:
        prefix = repo_id
    else:
        prefix = "ofpm"
    if repo_root.resolve() == base_path.resolve():
        suffix = dnf_safe_path_component(repo_root.name)
    else:
        suffix = dnf_safe_path_component(str(repo_root.resolve().relative_to(base_path.resolve())))
    return f"{prefix}-{suffix}"


def dnf_repo_file_path(
    repo_root: Path,
    base_path: Path,
    repo_id: str | None,
    repo_file: str | None,
    recursive: bool,
) -> Path:
    if repo_file:
        configured = Path(repo_file).expanduser().resolve()
        if recursive:
            return configured / f"{dnf_repo_id_for_root(base_path, repo_root, repo_id)}.repo"
        return configured
    repo_id_value = dnf_repo_id_for_root(base_path, repo_root, repo_id)
    return Path(f"/etc/yum.repos.d/{repo_id_value}.repo").resolve()


def cmd_apt_build_repo(args: argparse.Namespace) -> int:
    context = effective_apt_context(args)
    requested_package = args.package
    requested_version = args.version or apt_policy_version(requested_package)
    repo_root = Path(args.output).expanduser().resolve() if args.output else Path.cwd().resolve()
    pool_dir = repo_root / "pool"
    pool_dir.mkdir(parents=True, exist_ok=True)

    package_names = [requested_package]
    package_names.extend(apt_dependency_names(requested_package))
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

    try:
        local_repo_root = build_apt_local_repo_from_root(repo_root, requested_package)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"built apt local repo: {requested_package}")
    print(f" - version: {requested_version}")
    print(f" - distro: {context['distro']}")
    print(f" - release: {context['release']}")
    print(f" - arch: {context['arch']}")
    print(" - include dependencies: yes")
    print(f" - local repo root: {local_repo_root}")
    print(f" - pool dir: {pool_dir}")
    print(f" - package files: {len(downloaded_packages)}")
    print(f" - source line: {apt_source_line(local_repo_root)}")
    return 0


def cmd_apt_source_line(args: argparse.Namespace) -> int:
    repo_root = Path(args.path).expanduser().resolve()
    if not (repo_root / "Packages").exists() or not (repo_root / "Packages.gz").exists():
        print(f"apt local repo metadata not found: {repo_root}")
        print("hint: run `ofpm apt build-repo <package>` first")
        return 1
    print(apt_source_line(repo_root))
    return 0


def cmd_apt_activate(args: argparse.Namespace) -> int:
    base_path = Path(args.path).expanduser().resolve()
    recursive = bool(getattr(args, "recursive", False))
    repo_roots = find_apt_local_repo_roots(base_path) if recursive else [base_path]
    if not repo_roots or any(not ((repo_root / "Packages").exists() and (repo_root / "Packages.gz").exists()) for repo_root in repo_roots):
        print(f"apt local repo metadata not found: {base_path}")
        print("hint: run `ofpm apt build-repo <package>` first")
        return 1

    created_source_paths: list[Path] = []
    for local_repo_root in repo_roots:
        source_path = apt_source_file_path(
            local_repo_root,
            base_path,
            args.source_name,
            args.source_path,
            recursive,
        )
        try:
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(apt_source_line(local_repo_root) + "\n", encoding="utf-8")
        except PermissionError:
            print(f"permission denied writing apt source file: {source_path}")
            print("hint: run `sudo ofpm apt activate ...` or use `--source-path` under a writable directory")
            return 1

        print(f"activated apt local repo: {local_repo_root.name}")
        print(f" - local repo root: {local_repo_root}")
        print(f" - source file: {source_path}")
        print(f" - source line: {apt_source_line(local_repo_root)}")
        created_source_paths.append(source_path)

        access_issue = apt_repo_access_issue(local_repo_root)
        if access_issue:
            print(f" - apt cache refresh: skipped")
            print(f" - reason: {access_issue}")
            print(" - hint: move the repo to a world-traversable path or relax parent-directory execute permissions")
            return 1

    if not args.no_update:
        update_source_path = created_source_paths[0]
        try:
            isolated_apt_update(update_source_path)
        except subprocess.CalledProcessError as exc:
            print(" - apt cache refresh: failed")
            if exc.output:
                last_line = ""
                for line in exc.output.splitlines():
                    stripped = line.strip()
                    if stripped:
                        last_line = stripped
                if last_line:
                    print(f" - reason: {last_line}")
            return 1
        print(" - apt cache refresh: completed")
    else:
        print(" - apt cache refresh: skipped")
    return 0


def cmd_apt_deactivate(args: argparse.Namespace) -> int:
    base_path = Path(args.path).expanduser().resolve()
    recursive = bool(getattr(args, "recursive", False))
    repo_roots = find_apt_local_repo_roots(base_path) if recursive else [base_path]
    if not repo_roots:
        print(f"apt local repo not found: {base_path}")
        return 1

    removed_any = False
    first_source_path: Path | None = None
    for repo_root in repo_roots:
        source_path = apt_source_file_path(
            repo_root,
            base_path,
            args.source_name,
            args.source_path,
            recursive,
        )
        if not source_path.exists():
            continue
        try:
            source_path.unlink()
        except PermissionError:
            print(f"permission denied removing apt source file: {source_path}")
            print("hint: run `sudo ofpm apt deactivate ...` or remove a source file under a writable directory")
            return 1
        if first_source_path is None:
            first_source_path = source_path
        removed_any = True
        print(f"deactivated apt local repo: {repo_root.name}")
        print(f" - source file removed: {source_path}")

    if not removed_any:
        print(f"apt source files not found under: {base_path}")
        return 1

    if not args.no_update and first_source_path is not None:
        with contextlib.suppress(subprocess.CalledProcessError):
            isolated_apt_update(first_source_path)
        print(" - apt cache refresh: requested")
    else:
        print(" - apt cache refresh: skipped")
    return 0


def cmd_dnf_build_repo(args: argparse.Namespace) -> int:
    try:
        repo_root = build_dnf_local_repo(Path(args.path).expanduser().resolve())
    except ValueError as exc:
        print(str(exc))
        return 1
    repo_id = args.repo_id or dnf_repo_id_for_root(repo_root, repo_root, None)
    print(f"built dnf local repo: {repo_root.name}")
    print(f" - repo root: {repo_root}")
    print(f" - repo id: {repo_id}")
    print(f" - repo file preview path hint: /etc/yum.repos.d/{repo_id}.repo")
    return 0


def cmd_dnf_activate(args: argparse.Namespace) -> int:
    base_path = Path(args.path).expanduser().resolve()
    recursive = bool(getattr(args, "recursive", False))
    repo_roots = find_dnf_local_repo_roots(base_path) if recursive else [base_path]
    if not repo_roots:
        print(f"dnf local repo not found: {base_path}")
        print("hint: run `ofpm dnf build-repo <path>` first")
        return 1

    created_repo_ids: list[str] = []
    for repo_root in repo_roots:
        if not (repo_root / "repodata" / "repomd.xml").exists():
            print(f"dnf local repo metadata not found: {repo_root}")
            print("hint: run `ofpm dnf build-repo <path>` first")
            return 1
        repo_id = dnf_repo_id_for_root(base_path, repo_root, args.repo_id)
        repo_file_path = dnf_repo_file_path(repo_root, base_path, args.repo_id, args.repo_file, recursive)
        try:
            repo_file_path.parent.mkdir(parents=True, exist_ok=True)
            repo_file_path.write_text(dnf_repo_file_text(repo_id, repo_root), encoding="utf-8")
        except PermissionError:
            print(f"permission denied writing dnf repo file: {repo_file_path}")
            print("hint: run `sudo ofpm dnf activate ...` or use `--repo-file` under a writable directory")
            return 1
        print(f"activated dnf local repo: {repo_id}")
        print(f" - repo root: {repo_root}")
        print(f" - repo file: {repo_file_path}")
        created_repo_ids.append(repo_id)

    if not args.no_refresh and created_repo_ids:
        run_command_live(
            ["dnf", "makecache", "--disablerepo=*", *[f"--enablerepo={repo_id}" for repo_id in created_repo_ids]],
            label=f"dnf makecache {created_repo_ids[0]}",
        )
        print(" - dnf cache refresh: completed")
    else:
        print(" - dnf cache refresh: skipped")
    return 0


def cmd_dnf_deactivate(args: argparse.Namespace) -> int:
    base_path = Path(args.path).expanduser().resolve()
    recursive = bool(getattr(args, "recursive", False))
    repo_roots = find_dnf_local_repo_roots(base_path) if recursive else [base_path]
    if not repo_roots:
        print(f"dnf local repo not found: {base_path}")
        return 1

    removed_any = False
    for repo_root in repo_roots:
        repo_id = dnf_repo_id_for_root(base_path, repo_root, args.repo_id)
        repo_file_path = dnf_repo_file_path(repo_root, base_path, args.repo_id, args.repo_file, recursive)
        if not repo_file_path.exists():
            continue
        try:
            repo_file_path.unlink()
        except PermissionError:
            print(f"permission denied removing dnf repo file: {repo_file_path}")
            print("hint: run `sudo ofpm dnf deactivate ...` or remove a repo file under a writable directory")
            return 1
        print(f"deactivated dnf local repo: {repo_id}")
        print(f" - repo file removed: {repo_file_path}")
        removed_any = True

    if not removed_any:
        print(f"dnf repo files not found under: {base_path}")
        return 1
    return 0


def cmd_ollama_list(args: argparse.Namespace) -> int:
    from ofpm.ollama.cli import cmd_list

    return cmd_list(args)


def cmd_ollama_copy(args: argparse.Namespace) -> int:
    from ofpm.ollama.cli import cmd_copy

    return cmd_copy(args)


def cmd_ollama_verify(args: argparse.Namespace) -> int:
    from ofpm.ollama.cli import cmd_verify

    return cmd_verify(args)


def print_json(data: dict) -> None:
    import json

    print(json.dumps(data, indent=2, sort_keys=True))


def format_bytes(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def build_parser() -> argparse.ArgumentParser:
    parser = FriendlyArgumentParser(
        prog="ofpm",
        description=(
            "Personal offline package manager. Register a copied repo snapshot, "
            "then list, install, verify, upgrade, or remove packages without network access."
        ),
        epilog="""common target-side flow:
  ofpm repo add main /path/to/copied/repo
  ofpm list --all
  ofpm show <package>
  ofpm install <package>
  ofpm verify <package>

common builder-side flow:
  ofpm repo import main --path /path/to/payload --package <package> --version <version>
  ofpm prepare list
  ofpm prepare ollama latest --repo main
  ofpm apt build-repo <deb-package>
  ofpm apt list <apt-repo-path> --recursive

domain utilities:
  ofpm ollama list --models-dir ~/.ollama/models
  ofpm ollama copy llama3.2:3b --to /path/to/models

Use `ofpm <command> -h` for command-specific options.""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="<command>",
        parser_class=FriendlyArgumentParser,
    )

    def add_root_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--root",
            choices=["system", "user"],
            help="select the managed root kind; defaults to user for non-root users",
        )
        command_parser.add_argument(
            "--root-path",
            help="override the managed root path, mainly for tests or staged roots",
        )
        command_parser.add_argument(
            "--all-roots",
            action="store_true",
            help="query both user and system managed roots when supported",
        )

    def add_repo_query_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--repo", help="use one registered repo by id")
        command_parser.add_argument("--repo-path", help="query a repo snapshot directly without registering it")
        command_parser.add_argument("--repos-config", help="use a specific repo registry JSON file")

    def add_repos_config_option(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--repos-config", help="use a specific repo registry JSON file")

    init_parser = subparsers.add_parser("init", help="initialize local ofpm metadata")
    init_parser.set_defaults(func=cmd_init)

    list_parser = subparsers.add_parser("list", help="list available or installed packages")
    list_parser.add_argument("pattern", nargs="?", help="optional package name filter")
    list_parser.add_argument("--installed", action="store_true", help="show installed packages")
    list_parser.add_argument("--all", action="store_true", help="show every available package in selected repos")
    list_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    list_parser.add_argument("--verbose", action="store_true", help="show repo and package definition details")
    add_root_options(list_parser)
    add_repo_query_options(list_parser)
    list_parser.set_defaults(func=cmd_list)

    show_parser = subparsers.add_parser("show", help="show package metadata and availability")
    show_parser.add_argument("package", help="package id to inspect")
    show_parser.add_argument("--version", help="select a specific package version")
    show_parser.add_argument("--files", action="store_true", help="include package file declarations")
    show_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    add_root_options(show_parser)
    add_repo_query_options(show_parser)
    show_parser.set_defaults(func=cmd_show)

    install_parser = subparsers.add_parser("install", help="install a package from an offline repo")
    install_parser.add_argument("package", help="package id to install")
    install_parser.add_argument("--version", help="install a specific version")
    add_root_options(install_parser)
    add_repo_query_options(install_parser)
    install_parser.set_defaults(func=cmd_install)

    reinstall_parser = subparsers.add_parser("reinstall", help="remove and install a package again")
    reinstall_parser.add_argument("package", help="package id to reinstall")
    reinstall_parser.add_argument("--version", help="reinstall a specific version")
    add_root_options(reinstall_parser)
    add_repo_query_options(reinstall_parser)
    reinstall_parser.set_defaults(func=cmd_reinstall)

    upgrade_parser = subparsers.add_parser("upgrade", help="upgrade an installed package from a repo")
    upgrade_parser.add_argument("package", help="package id to upgrade")
    upgrade_parser.add_argument("--version", help="upgrade to a specific version")
    add_root_options(upgrade_parser)
    add_repo_query_options(upgrade_parser)
    upgrade_parser.set_defaults(func=cmd_upgrade)

    remove_parser = subparsers.add_parser("remove", help="remove an installed package using its receipt")
    remove_parser.add_argument("package", help="package id to remove")
    add_root_options(remove_parser)
    add_repo_query_options(remove_parser)
    remove_parser.set_defaults(func=cmd_remove)

    verify_pkg_parser = subparsers.add_parser("verify", help="verify installed files and package state")
    verify_pkg_parser.add_argument("package", help="package id to verify")
    verify_pkg_parser.add_argument("--target-root", help="check files under a specific target root")
    verify_pkg_parser.add_argument("--strict-modes", action="store_true", help="treat file mode differences as failures")
    add_root_options(verify_pkg_parser)
    add_repo_query_options(verify_pkg_parser)
    verify_pkg_parser.set_defaults(func=cmd_verify)

    verify_source_parser = subparsers.add_parser("verify-source", help="verify package source files in a repo")
    verify_source_parser.add_argument("package", help="package id to verify")
    verify_source_parser.add_argument("--version", help="verify a specific package version")
    add_repo_query_options(verify_source_parser)
    verify_source_parser.set_defaults(func=cmd_verify_source)

    state_parser = subparsers.add_parser("state", help="show managed-root installed state")
    state_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    add_root_options(state_parser)
    state_parser.set_defaults(func=cmd_state)

    env_parser = subparsers.add_parser("env", help="render shell or module environment for an installed package")
    env_parser.add_argument("subject", nargs="?", help="environment subject, usually `package`")
    env_parser.add_argument("package_name", nargs="?", help="installed package id")
    env_parser.add_argument("--root", choices=["system", "user"], help="select the managed root kind")
    env_parser.add_argument("--root-path", help="override the managed root path")
    env_parser.add_argument("--export", action="store_true", help="include shell export statements")
    env_parser.add_argument("--format", choices=["bash", "modulefile"], default="bash", help="output format")
    env_parser.set_defaults(func=cmd_env)

    plugin_parser = subparsers.add_parser("plugin", help="manage optional package integrations")
    plugin_subparsers = plugin_parser.add_subparsers(
        dest="plugin_command",
        required=True,
        parser_class=FriendlyArgumentParser,
    )

    plugin_list_parser = plugin_subparsers.add_parser("list", help="list plugins attached to a host package")
    plugin_list_parser.add_argument("host_package", help="host package id")
    add_root_options(plugin_list_parser)
    plugin_list_parser.set_defaults(func=cmd_plugin_list)

    plugin_attach_parser = plugin_subparsers.add_parser("attach", help="attach a plugin package to a host package")
    plugin_attach_parser.add_argument("host_package", help="host package id")
    plugin_attach_parser.add_argument("plugin_package", help="plugin package id")
    add_root_options(plugin_attach_parser)
    plugin_attach_parser.set_defaults(func=cmd_plugin_attach)

    plugin_detach_parser = plugin_subparsers.add_parser("detach", help="detach a plugin package from a host package")
    plugin_detach_parser.add_argument("host_package", help="host package id")
    plugin_detach_parser.add_argument("plugin_package", help="plugin package id")
    add_root_options(plugin_detach_parser)
    plugin_detach_parser.set_defaults(func=cmd_plugin_detach)

    plugin_refresh_parser = plugin_subparsers.add_parser("refresh", help="refresh plugin integration state")
    plugin_refresh_parser.add_argument("host_package", nargs="?", help="optional host package id")
    add_root_options(plugin_refresh_parser)
    plugin_refresh_parser.set_defaults(func=cmd_plugin_refresh)

    def configure_install_ofpm_parser(current_parser: argparse.ArgumentParser) -> None:
        current_parser.add_argument("output", nargs="?", help="optional installation output directory")
        current_parser.add_argument("--python", help="python executable to write into the launcher")
        current_parser.add_argument("--source-root", help="source tree to launch as ofpm")
        current_parser.add_argument("--root", choices=["system", "user"], help="install under the selected managed root")
        current_parser.add_argument("--profile-path", help="shell profile file to update")
        current_parser.add_argument("--bashrc-path", help="bashrc file to update")
        current_parser.add_argument("--symlink-path", help="launcher symlink path to create")
        current_parser.add_argument("--no-profile", action="store_true", help="do not update shell profile files")
        current_parser.add_argument("--no-symlink", action="store_true", help="do not create a launcher symlink")
        current_parser.add_argument("--force", action="store_true", help="overwrite existing launcher files")
        current_parser.set_defaults(func=cmd_install_cli)

    def configure_reinstall_ofpm_parser(current_parser: argparse.ArgumentParser) -> None:
        configure_install_ofpm_parser(current_parser)
        current_parser.set_defaults(func=cmd_reinstall_cli)

    install_ofpm_parser = subparsers.add_parser("install-ofpm", help="install the ofpm CLI launcher")
    configure_install_ofpm_parser(install_ofpm_parser)

    reinstall_ofpm_parser = subparsers.add_parser("reinstall-ofpm", help="reinstall the ofpm CLI launcher")
    configure_reinstall_ofpm_parser(reinstall_ofpm_parser)

    install_cli_parser = subparsers.add_parser("install-cli", help="install the ofpm CLI launcher")
    configure_install_ofpm_parser(install_cli_parser)

    package_parser = subparsers.add_parser("package", help="create, verify, or test package recipes")
    package_subparsers = package_parser.add_subparsers(
        dest="package_command",
        required=True,
        parser_class=FriendlyArgumentParser,
    )

    package_verify_parser = package_subparsers.add_parser("verify", help="verify a package recipe directory")
    package_verify_parser.add_argument("path", help="path to a package recipe directory")
    package_verify_parser.set_defaults(func=cmd_package_verify)

    package_test_parser = package_subparsers.add_parser("test", help="run a package recipe test install")
    package_test_parser.add_argument("path", help="path to a package recipe directory")
    package_test_parser.add_argument("--root", choices=["system", "user"], help="managed root kind to simulate")
    package_test_parser.set_defaults(func=cmd_package_test)

    package_init_parser = package_subparsers.add_parser("init", help="scaffold a package recipe directory")
    package_init_parser.add_argument("path", help="directory where package.py and payload will be created")
    package_init_parser.add_argument("--package-id", required=True, help="package id for the new recipe")
    package_init_parser.add_argument("--version", default="1.0.0", help="package version")
    package_init_parser.add_argument("--profile", default="ubuntu-22.04", help="target profile id")
    package_init_parser.add_argument("--install-root", help="managed-root relative install location")
    package_init_parser.add_argument("--description", help="short package description")
    package_init_parser.add_argument("--force", action="store_true", help="overwrite an existing recipe")
    package_init_parser.set_defaults(func=cmd_package_init)

    prepare_parser = subparsers.add_parser("prepare", help="prepare external artifacts for an offline repo")
    prepare_subparsers = prepare_parser.add_subparsers(
        dest="prepare_command",
        required=True,
        parser_class=FriendlyArgumentParser,
    )

    prepare_list_parser = prepare_subparsers.add_parser("list", help="list artifact preparers")
    prepare_list_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    prepare_list_parser.set_defaults(func=cmd_prepare_list)

    def add_prepare_output_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--repo", help="registered repo id to import into")
        command_parser.add_argument("--repo-dir", help="repo snapshot directory to import into directly")
        command_parser.add_argument("--repos-config", help="use a specific repo registry JSON file")
        command_parser.add_argument("--work-dir", help="keep prepared package staging under this directory")
        command_parser.add_argument("--replace", action="store_true", help="replace an existing package version")

    for preparer_id in ["ollama", "pi-agent"]:
        item_parser = prepare_subparsers.add_parser(preparer_id, help=f"prepare {preparer_id} artifacts")
        item_parser.add_argument("action", help="`list`, `latest`, or a concrete version")
        item_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON for `list`")
        add_prepare_output_options(item_parser)
        item_parser.set_defaults(func=cmd_prepare_item, preparer_id=preparer_id)

    repo_parser = subparsers.add_parser("repo", help="register and inspect offline repo snapshots")
    repo_subparsers = repo_parser.add_subparsers(
        dest="repo_command",
        required=True,
        parser_class=FriendlyArgumentParser,
    )

    repo_list_parser = repo_subparsers.add_parser("list", help="list registered repos")
    repo_list_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    add_repos_config_option(repo_list_parser)
    repo_list_parser.set_defaults(func=cmd_repo_list)

    repo_add_parser = repo_subparsers.add_parser("add", help="register a copied repo snapshot")
    repo_add_parser.add_argument("repo_id", help="local repo id, for example `main`")
    repo_add_parser.add_argument("path", help="path to the repo snapshot")
    add_repos_config_option(repo_add_parser)
    repo_add_parser.set_defaults(func=cmd_repo_add)

    repo_remove_parser = repo_subparsers.add_parser("remove", help="remove a repo registration")
    repo_remove_parser.add_argument("repo_id", help="registered repo id")
    add_repos_config_option(repo_remove_parser)
    repo_remove_parser.set_defaults(func=cmd_repo_remove)

    repo_show_parser = repo_subparsers.add_parser("show", help="show a registered repo path and status")
    repo_show_parser.add_argument("repo_id", help="registered repo id")
    add_repos_config_option(repo_show_parser)
    repo_show_parser.set_defaults(func=cmd_repo_show)

    repo_import_parser = repo_subparsers.add_parser("import", help="import a local payload directory into a repo")
    repo_import_parser.add_argument("repo_id", help="registered repo id to import into")
    repo_import_parser.add_argument("--path", required=True, help="local payload directory to import")
    repo_import_parser.add_argument("--package", help="package id; defaults from metadata or source directory")
    repo_import_parser.add_argument("--version", help="package version")
    repo_import_parser.add_argument("--profile", help="target profile id")
    repo_import_parser.add_argument("--install-root", help="managed-root relative install location")
    repo_import_parser.add_argument("--description", help="short package description")
    repo_import_parser.add_argument("--meta", help="metadata JSON file to seed package fields")
    add_repos_config_option(repo_import_parser)
    repo_import_parser.set_defaults(func=cmd_repo_import)

    repo_import_archive_parser = repo_subparsers.add_parser("import-archive", help="import an archive into a repo")
    repo_import_archive_parser.add_argument("repo_id", help="registered repo id to import into")
    repo_import_archive_parser.add_argument("--archive", required=True, help="archive file to unpack and import")
    repo_import_archive_parser.add_argument("--package", help="package id; defaults from metadata or archive name")
    repo_import_archive_parser.add_argument("--version", help="package version")
    repo_import_archive_parser.add_argument("--profile", help="target profile id")
    repo_import_archive_parser.add_argument("--install-root", help="managed-root relative install location")
    repo_import_archive_parser.add_argument("--description", help="short package description")
    repo_import_archive_parser.add_argument("--meta", help="metadata JSON file to seed package fields")
    add_repos_config_option(repo_import_archive_parser)
    repo_import_archive_parser.set_defaults(func=cmd_repo_import_archive)

    repo_import_package_parser = repo_subparsers.add_parser("import-package", help="copy an existing package recipe into a repo")
    repo_import_package_parser.add_argument("repo_id", help="registered repo id to import into")
    repo_import_package_parser.add_argument("path", help="path to an existing package recipe directory")
    repo_import_package_parser.add_argument("--replace", action="store_true", help="replace an existing package version")
    add_repos_config_option(repo_import_package_parser)
    repo_import_package_parser.set_defaults(func=cmd_repo_import_package)

    apt_parser = subparsers.add_parser("apt", help="builder-side helpers for apt provider snapshots")
    apt_parser.set_defaults(func=cmd_apt_help, _apt_parser=apt_parser)
    apt_subparsers = apt_parser.add_subparsers(
        dest="apt_command",
        parser_class=FriendlyArgumentParser,
    )

    apt_list_parser = apt_subparsers.add_parser("list", help="list packages in a local apt repo")
    apt_list_parser.add_argument("path", nargs="?", default=".", help="local apt repo root or parent directory")
    apt_list_parser.add_argument("--pattern", help="optional apt package name filter")
    apt_list_parser.add_argument("--recursive", action="store_true", help="inspect nested apt repos under path")
    apt_list_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    apt_list_parser.add_argument("--verbose", action="store_true", help="show repo root and file details")
    apt_list_parser.set_defaults(func=cmd_apt_list)

    apt_show_parser = apt_subparsers.add_parser("show", help="show a package in local apt repo metadata")
    apt_show_parser.add_argument("package", help="apt package name")
    apt_show_parser.add_argument("path", nargs="?", default=".", help="local apt repo root or parent directory")
    apt_show_parser.add_argument("--version", help="select a specific apt package version")
    apt_show_parser.add_argument("--recursive", action="store_true", help="inspect nested apt repos under path")
    apt_show_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    apt_show_parser.set_defaults(func=cmd_apt_show)

    apt_commands_parser = apt_subparsers.add_parser("commands", help="write apt commands for acquiring a package")
    apt_commands_parser.add_argument("package", help="apt package name")
    apt_commands_parser.add_argument("--version", help="apt package version")
    apt_commands_parser.add_argument("--output", help="write commands to a file")
    apt_commands_parser.add_argument("--source-name", help="apt source name to use in generated commands")
    apt_commands_parser.set_defaults(func=cmd_apt_commands)

    apt_build_repo_parser = apt_subparsers.add_parser("build-repo", help="download apt artifacts into an ofpm repo")
    apt_build_repo_parser.add_argument("package", help="apt package name")
    apt_build_repo_parser.add_argument("--version", help="apt package version")
    apt_build_repo_parser.add_argument("--distro", help="target distro id")
    apt_build_repo_parser.add_argument("--release", help="target distro release")
    apt_build_repo_parser.add_argument("--arch", help="target architecture")
    apt_build_repo_parser.add_argument("--output", help="repo output directory")
    apt_build_repo_parser.set_defaults(func=cmd_apt_build_repo)

    apt_source_line_parser = apt_subparsers.add_parser("source-line", help="print a file:// apt source line")
    apt_source_line_parser.add_argument("path", help="path to an apt repo snapshot")
    apt_source_line_parser.set_defaults(func=cmd_apt_source_line)

    apt_activate_parser = apt_subparsers.add_parser("activate", help="activate a local apt repo snapshot")
    apt_activate_parser.add_argument("path", help="path to an apt repo snapshot")
    apt_activate_parser.add_argument("--recursive", action="store_true", help="activate nested apt repo snapshots")
    apt_activate_parser.add_argument("--source-name", help="apt source list name")
    apt_activate_parser.add_argument("--source-path", help="source list file path")
    apt_activate_parser.add_argument("--no-update", action="store_true", help="skip apt update after activation")
    apt_activate_parser.set_defaults(func=cmd_apt_activate)

    apt_deactivate_parser = apt_subparsers.add_parser("deactivate", help="deactivate a local apt repo snapshot")
    apt_deactivate_parser.add_argument("path", help="path to an apt repo snapshot")
    apt_deactivate_parser.add_argument("--recursive", action="store_true", help="deactivate nested apt repo snapshots")
    apt_deactivate_parser.add_argument("--source-name", help="apt source list name")
    apt_deactivate_parser.add_argument("--source-path", help="source list file path")
    apt_deactivate_parser.add_argument("--no-update", action="store_true", help="skip apt update after deactivation")
    apt_deactivate_parser.set_defaults(func=cmd_apt_deactivate)

    ollama_parser = subparsers.add_parser("ollama", help="utilities for Ollama model stores")
    ollama_subparsers = ollama_parser.add_subparsers(
        dest="ollama_command",
        required=True,
        parser_class=FriendlyArgumentParser,
    )

    ollama_list_parser = ollama_subparsers.add_parser("list", help="list models in an Ollama models directory")
    ollama_list_parser.add_argument("--models-dir", help="Ollama models directory; defaults to OLLAMA_MODELS or ~/.ollama/models")
    ollama_list_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ollama_list_parser.add_argument("--verbose", action="store_true", help="show manifest paths and full refs")
    ollama_list_parser.set_defaults(func=cmd_ollama_list)

    ollama_copy_parser = ollama_subparsers.add_parser("copy", help="copy one Ollama model closure to another models directory")
    ollama_copy_parser.add_argument("model", help="model ref, for example llama3.2:3b")
    ollama_copy_parser.add_argument("--from", dest="source", help="source models directory; defaults to OLLAMA_MODELS or ~/.ollama/models")
    ollama_copy_parser.add_argument("--to", dest="target", required=True, help="target models directory")
    ollama_copy_parser.add_argument("--dry-run", action="store_true", help="show what would be copied without writing files")
    ollama_copy_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ollama_copy_parser.set_defaults(func=cmd_ollama_copy)

    ollama_verify_parser = ollama_subparsers.add_parser("verify", help="verify one Ollama model manifest and referenced blobs")
    ollama_verify_parser.add_argument("model", help="model ref, for example llama3.2:3b")
    ollama_verify_parser.add_argument("--models-dir", help="Ollama models directory; defaults to OLLAMA_MODELS or ~/.ollama/models")
    ollama_verify_parser.add_argument("--no-hash", action="store_true", help="check file presence only, without sha256 hashing")
    ollama_verify_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ollama_verify_parser.set_defaults(func=cmd_ollama_verify)

    dnf_parser = subparsers.add_parser("dnf", help="helpers for local dnf/yum repo snapshots")
    dnf_subparsers = dnf_parser.add_subparsers(
        dest="dnf_command",
        required=True,
        parser_class=FriendlyArgumentParser,
    )

    dnf_build_repo_parser = dnf_subparsers.add_parser("build-repo", help="create dnf repo metadata for a directory")
    dnf_build_repo_parser.add_argument("path", help="directory containing RPM artifacts")
    dnf_build_repo_parser.add_argument("--repo-id", help="repo id to write into metadata")
    dnf_build_repo_parser.set_defaults(func=cmd_dnf_build_repo)

    dnf_activate_parser = dnf_subparsers.add_parser("activate", help="activate a local dnf repo snapshot")
    dnf_activate_parser.add_argument("path", help="path to a dnf repo snapshot")
    dnf_activate_parser.add_argument("--recursive", action="store_true", help="activate nested dnf repo snapshots")
    dnf_activate_parser.add_argument("--repo-id", help="dnf repo id")
    dnf_activate_parser.add_argument("--repo-file", help="repo file path")
    dnf_activate_parser.add_argument("--no-refresh", action="store_true", help="skip dnf cache refresh")
    dnf_activate_parser.set_defaults(func=cmd_dnf_activate)

    dnf_deactivate_parser = dnf_subparsers.add_parser("deactivate", help="deactivate a local dnf repo snapshot")
    dnf_deactivate_parser.add_argument("path", help="path to a dnf repo snapshot")
    dnf_deactivate_parser.add_argument("--recursive", action="store_true", help="deactivate nested dnf repo snapshots")
    dnf_deactivate_parser.add_argument("--repo-id", help="dnf repo id")
    dnf_deactivate_parser.add_argument("--repo-file", help="repo file path")
    dnf_deactivate_parser.set_defaults(func=cmd_dnf_deactivate)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
