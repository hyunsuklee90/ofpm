from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofpm.installers import (
    install_package_from_definition,
    remove_package_from_definition,
    verify_package_from_definition,
)
from ofpm.package_def import dump_package_file, load_package_file
from ofpm.repo_data import native_repo_package_root, package_summary_from_manifest, verify_package_sources
from ofpm.state_db import managed_state_file


@dataclass
class LocalPackage:
    manifest_path: Path
    package_root: Path
    package_data: dict[str, Any]


def resolve_local_package(path: str | Path) -> LocalPackage:
    candidate = Path(path).expanduser().resolve()
    manifest_path = candidate
    if candidate.is_dir():
        py_manifest = candidate / "package.py"
        json_manifest = candidate / "package.json"
        if py_manifest.exists():
            manifest_path = py_manifest
        elif json_manifest.exists():
            manifest_path = json_manifest
        else:
            raise ValueError(f"package definition not found under: {candidate}")
    if not manifest_path.exists():
        raise ValueError(f"package path not found: {manifest_path}")
    package_data = load_package_file(manifest_path)
    return LocalPackage(
        manifest_path=manifest_path,
        package_root=manifest_path.parent,
        package_data=package_data,
    )


def verify_local_package(path: str | Path) -> dict[str, Any]:
    package = resolve_local_package(path)
    summary = package_summary_from_manifest(package.manifest_path)
    source_check = verify_package_sources(package.manifest_path)
    return {
        "package_id": package.package_data["package_id"],
        "version": package.package_data["version"],
        "manifest": str(package.manifest_path),
        "package_root": str(package.package_root),
        "install_root": package.package_data["install_root"],
        "file_count": summary["file_count"],
        "available": summary["available"],
        "availability_error": summary["availability_error"],
        "missing_sources": summary["missing_sources"],
        "missing_files": source_check["missing_files"],
        "declared_source_count": source_check["declared_source_count"],
        "expanded_file_count": source_check["expanded_file_count"],
        "ok": summary["available"] and source_check["ok"],
    }


def test_local_package(path: str | Path, *, root_kind: str = "user") -> dict[str, Any]:
    package = resolve_local_package(path)
    with tempfile.TemporaryDirectory(prefix="ofpm-package-test-") as temp_dir:
        managed_root = Path(temp_dir) / "managed-root"
        state = install_package_from_definition(
            managed_root,
            package.manifest_path,
            package.package_data,
            root_kind=root_kind,
        )
        installed_state_path = managed_state_file(managed_root, package.package_data["package_id"])
        installed = {
            "package_id": package.package_data["package_id"],
            "package_version": package.package_data["version"],
            "install_root": package.package_data["install_root"],
            "tracked_file_count": len(state["package"].get("tracked_files", [])),
            "state_path": str(installed_state_path),
            "selected_root_kind": root_kind,
            "managed_root": str(managed_root),
            "raw": state,
        }
        errors = verify_package_from_definition(
            managed_root,
            package.manifest_path,
            package.package_data,
            installed,
            root_kind=root_kind,
        )
        if errors is None:
            errors = []
        removed = remove_package_from_definition(
            managed_root,
            package.manifest_path,
            package.package_data,
            installed,
            root_kind=root_kind,
        )
        return {
            "package_id": package.package_data["package_id"],
            "version": package.package_data["version"],
            "manifest": str(package.manifest_path),
            "managed_root": str(managed_root),
            "tracked_files": len(state["package"].get("tracked_files", [])),
            "verify_errors": errors,
            "removed": removed is not None,
            "version_root": state["package"].get("version_root", ""),
            "current_path": state["package"].get("current_path", ""),
        }


def scaffold_managed_files_package(
    package_root: str | Path,
    *,
    package_id: str,
    version: str,
    profile_id: str,
    install_root: str | None = None,
    description: str = "",
    force: bool = False,
) -> Path:
    root = Path(package_root).expanduser().resolve()
    manifest_path = root / "package.py"
    payload_root = root / "payload"
    if not force and (manifest_path.exists() or payload_root.exists()):
        raise ValueError(f"package root already initialized: {root}")
    if force and root.exists():
        shutil.rmtree(root)
    payload_root.mkdir(parents=True, exist_ok=True)
    install_root_value = install_root or f"payloads/{package_id}/{version}"
    distro, _, release = profile_id.partition("-")
    dump_package_file(
        manifest_path,
        {
            "schema_version": "1",
            "package_id": package_id,
            "version": version,
            "target": {
                "os": "linux",
                "distro": distro,
                "release": release,
                "arch": "amd64",
            },
            "install_root": install_root_value,
            "depends": [],
            "plugins": [],
            "plugin_data": [],
            "metadata": {
                "description": description,
            },
            "env": {},
            "files": [
                {
                    "source_dir": "payload",
                    "target_dir": "",
                }
            ],
        },
    )
    return root


def import_local_package(
    repo_path: Path,
    package_path: str | Path,
    *,
    replace: bool = False,
) -> tuple[LocalPackage, Path]:
    package = resolve_local_package(package_path)
    package_id = package.package_data["package_id"]
    version = package.package_data["version"]
    dest_root = native_repo_package_root(repo_path) / package_id / version
    if dest_root.exists():
        if not replace:
            raise ValueError(f"package already exists in repo: {dest_root}")
        shutil.rmtree(dest_root)
    dest_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package.package_root, dest_root)
    return package, dest_root
