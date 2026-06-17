from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from ofpm.repo_data import (
    expanded_package_entries,
    find_installed_state,
    managed_state_root,
    resolve_source_path,
)
from ofpm.state_db import dump_json, managed_state_file, record_install, record_removal, utc_now


def progress(message: str) -> None:
    print(message, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_bytes(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def normalize_mode(mode: str | None, source: Path) -> str:
    if mode:
        return mode
    return format(source.stat().st_mode & 0o777, "04o")


def relative_target_path(install_root: str, target: str) -> str:
    clean_install_root = install_root.strip("/").replace("\\", "/")
    clean_target = target.strip("/").replace("\\", "/")
    return "/".join(part for part in [clean_install_root, clean_target] if part)


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


def public_bin_dir(managed_root: Path) -> Path:
    return managed_root / "bin"


def normalize_system_ownership(path: Path, *, root_kind: str) -> None:
    geteuid = getattr(os, "geteuid", None)
    if root_kind != "system" or not callable(geteuid) or geteuid() != 0:
        return

    def chown_current(item: Path) -> None:
        if item.is_symlink():
            os.lchown(item, 0, 0)
            return
        os.chown(item, 0, 0)

    if not path.exists() and not path.is_symlink():
        return
    chown_current(path)
    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.rglob("*")):
            chown_current(child)


def expose_public_executables(managed_root: Path, executables: list[str]) -> list[str]:
    bin_dir = public_bin_dir(managed_root)
    bin_dir.mkdir(parents=True, exist_ok=True)
    public_links: list[str] = []
    for executable in executables:
        source_path = Path(executable)
        link_path = bin_dir / source_path.name
        public_links.append(str(link_path))
        if link_path.is_symlink():
            current_target = Path(os.readlink(link_path))
            if current_target == source_path:
                continue
            raise FileExistsError(
                f"public executable already provided by another package: {link_path} -> {current_target}"
            )
        if link_path.exists():
            raise FileExistsError(f"public executable path already exists and is not a symlink: {link_path}")
        link_path.symlink_to(source_path, target_is_directory=False)
    return public_links


def remove_public_executables(installed_state: dict[str, Any]) -> None:
    package = installed_state["raw"]["package"]
    public_links = package.get("public_executables", [])
    executables = package.get("executables", [])
    expected_links = dict(zip(public_links, executables, strict=False))
    for link_text, target_text in expected_links.items():
        link_path = Path(link_text)
        if not link_path.is_symlink():
            continue
        current_target = Path(os.readlink(link_path))
        expected_target = Path(target_text)
        if current_target == expected_target:
            link_path.unlink()


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
    source_artifacts = sorted({str(Path(item["source"]).resolve()) for item in entries})
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
        normalize_system_ownership(destination, root_kind=root_kind)
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
    normalize_system_ownership(current_link, root_kind=root_kind)
    progress(f"[ofpm] install {package_id}@{version}: activated current link")
    progress(f"  current link: {current_link} -> {version_root}")
    public_executables = expose_public_executables(managed_root, executables)
    if public_executables:
        progress(f"[ofpm] install {package_id}@{version}: exposed public executables")
        for public_link in public_executables:
            progress(f"  public link: {public_link}")

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
            "public_executables": public_executables,
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


def _tracked_files_for_tree(
    version_root: Path,
    install_root: str,
    *,
    exclude_roots: set[Path] | None = None,
) -> list[dict[str, Any]]:
    excluded = {path.resolve() for path in (exclude_roots or set())}
    tracked_files: list[dict[str, Any]] = []
    for file_path in sorted(version_root.rglob("*")):
        if not file_path.is_file():
            continue
        resolved = file_path.resolve()
        if any(resolved == root or root in resolved.parents for root in excluded):
            continue
        relpath = file_path.relative_to(version_root).as_posix()
        tracked_files.append(
            {
                "install_path": relative_target_path(install_root, relpath),
                "sha256": sha256_file(file_path),
                "size": file_path.stat().st_size,
                "mode": format(file_path.stat().st_mode & 0o777, "04o"),
            }
        )
    return tracked_files


def _current_target_for_extracted_archive(version_root: Path, *, exclude_names: set[str] | None = None) -> Path:
    excluded = exclude_names or set()
    children = [entry for entry in version_root.iterdir() if entry.name not in excluded]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return version_root


def extract_archive(archive_path: Path, destination: Path) -> None:
    name = archive_path.name
    if name.endswith((".tar.zst", ".tzst")):
        subprocess.run(
            ["tar", "--zstd", "-xf", str(archive_path), "-C", str(destination)],
            check=True,
        )
        return
    with tarfile.open(archive_path, "r:*") as archive:
        archive.extractall(destination)


def install_archive_extract_package(
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
    artifacts_root = version_root / "artifacts"

    progress(f"[ofpm] install {package_id}@{version}: preparing managed root")
    progress(f"  manifest: {package_manifest}")
    progress(f"  managed root: {managed_root}")
    progress(f"  version root: {version_root}")
    progress(f"  root kind: {root_kind}")
    progress("  package intent: generic archive extract payload")

    dependency_errors = required_dependency_errors(managed_root, package_data)
    if dependency_errors:
        raise ValueError("; ".join(dependency_errors))

    if version_root.exists():
        raise FileExistsError(f"package version already installed at {version_root}")

    entries = expanded_package_entries(package_data, package_manifest, artifact_roots=artifact_roots)
    if len(entries) != 1:
        raise ValueError("archive extract install expects exactly one source artifact")

    archive_source = Path(entries[0]["source"]).resolve()
    archive_size = archive_source.stat().st_size
    progress(f"[ofpm] install {package_id}@{version}: selected archive")
    progress(f"  archive source: {archive_source}")
    progress(f"  archive size: {archive_size} bytes ({format_bytes(archive_size)})")
    managed_root.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=False)

    archive_dest = artifacts_root / archive_source.name
    shutil.copy2(archive_source, archive_dest)
    normalize_system_ownership(archive_dest, root_kind=root_kind)
    progress(f"  stored archive: {archive_dest}")

    progress(f"[ofpm] install {package_id}@{version}: extracting archive")
    extract_archive(archive_dest, version_root)
    normalize_system_ownership(version_root, root_kind=root_kind)

    current_target = _current_target_for_extracted_archive(version_root, exclude_names={"artifacts"})
    reset_current_link(current_link, current_target)
    normalize_system_ownership(current_link, root_kind=root_kind)
    progress(f"[ofpm] install {package_id}@{version}: activated current link")
    progress(f"  current link: {current_link} -> {current_target}")

    executables: list[str] = []
    bin_dir = current_link / "bin"
    if bin_dir.exists():
        for candidate in sorted(bin_dir.iterdir()):
            if candidate.is_file():
                executables.append(str(candidate))

    public_executables = expose_public_executables(managed_root, executables)
    if public_executables:
        progress(f"[ofpm] install {package_id}@{version}: exposed public executables")
        for public_link in public_executables:
            progress(f"  public link: {public_link}")

    tracked_files = _tracked_files_for_tree(version_root, package_data["install_root"], exclude_roots={artifacts_root})

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
            "public_executables": public_executables,
            "tracked_files": tracked_files,
            "install_mode": "archive",
            "artifacts": [
                {
                    "source": str(archive_source),
                    "stored_path": str(archive_dest),
                    "sha256": sha256_file(archive_dest),
                    "size": archive_dest.stat().st_size,
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
            "executables": executables,
            "artifacts_root": str(artifacts_root),
        },
        artifact_ref={"type": "stored-artifact", "paths": state["package"]["artifacts"]},
    )
    progress(f"[ofpm] install {package_id}@{version}: recorded installed state")
    progress(f"  state file: {state_file}")
    return state


def remove_managed_payload(
    managed_root: Path,
    installed_state: dict[str, Any],
) -> dict[str, Any]:
    package = installed_state["raw"]["package"]
    version_root = Path(package["version_root"])
    current_path = Path(package["current_path"])
    package_payload_root = version_root.parent

    if current_path.is_symlink():
        try:
            resolved_target = current_path.resolve()
            if resolved_target == version_root.resolve() or version_root.resolve() in resolved_target.parents:
                current_path.unlink()
        except FileNotFoundError:
            current_path.unlink()

    remove_public_executables(installed_state)

    if version_root.exists():
        shutil.rmtree(version_root)

    removed_package_payload_root = False
    payloads_root = managed_root / "payloads"
    if package_payload_root != payloads_root and package_payload_root.exists():
        try:
            package_payload_root.rmdir()
            removed_package_payload_root = True
        except OSError:
            removed_package_payload_root = False

    record_removal(managed_root, installed_state)

    return {
        "package_id": package["package_id"],
        "package_version": package["package_version"],
        "managed_root": str(managed_root),
        "removed_version_root": str(version_root),
        "removed_package_payload_root": str(package_payload_root) if removed_package_payload_root else "",
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


def verify_managed_files_install(installed_state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    managed_root = Path(installed_state["raw"].get("managed_root", ""))
    state_path = Path(installed_state["state_path"])
    if not managed_root.exists():
        errors.append(f"missing managed root: {managed_root}")
        return errors
    from ofpm.core import verify_state

    errors.extend(verify_state(managed_root, state_path))
    for executable in installed_state["raw"]["package"].get("executables", []):
        path = Path(executable)
        if not path.exists():
            errors.append(f"missing executable: {path}")
            continue
        if not os.access(path, os.X_OK):
            errors.append(f"not executable: {path}")
    return errors
