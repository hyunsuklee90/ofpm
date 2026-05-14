from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ofpm.package_def import load_package_file


def safe_path_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "item"


def read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value.strip().strip('"')
    return data


def detect_apt_context() -> dict[str, str]:
    os_release = read_os_release()
    distro = os_release.get("ID", "ubuntu").strip().lower() or "ubuntu"
    release = os_release.get("VERSION_ID", "").strip() or "unknown"
    try:
        arch = subprocess.run(
            ["dpkg", "--print-architecture"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        arch = "amd64"
    return {"distro": distro, "release": release, "arch": arch}


def apt_catalog_root(repo_root: Path) -> Path:
    return repo_root / "apt"


def apt_package_manifest_path(repo_root: Path, package_name: str, version: str) -> Path:
    return apt_catalog_root(repo_root) / package_name / safe_path_component(version) / "package.py"


def apt_artifact_root(
    repo_root: Path,
    distro: str,
    release: str,
    arch: str,
    package_name: str,
    version: str,
) -> Path:
    return apt_catalog_root(repo_root) / package_name / safe_path_component(version) / "payload"


def apt_package_manifests(repo_root: Path) -> list[Path]:
    results = sorted(apt_catalog_root(repo_root).glob("*/*/package.py"))
    if results:
        return results
    return sorted(apt_catalog_root(repo_root).glob("*/*/package.json"))


def find_apt_package_manifest(
    repo_root: Path,
    package_name: str,
    version: str | None = None,
) -> Path | None:
    matches = [
        manifest_path
        for manifest_path in apt_package_manifests(repo_root)
        if load_package_file(manifest_path).get("package_name") == package_name
    ]
    if not matches:
        return None
    if version is not None:
        for manifest_path in matches:
            data = load_package_file(manifest_path)
            if data.get("package_version") == version:
                return manifest_path
        return None
    return sorted(matches, key=lambda path: load_package_file(path).get("package_version", ""))[-1]


def list_apt_packages(repo_root: Path) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for manifest_path in apt_package_manifests(repo_root):
        data = load_package_file(manifest_path)
        packages.append(
            {
                "package_name": data["package_name"],
                "package_version": data["package_version"],
                "distro": data["context"]["distro"],
                "release": data["context"]["release"],
                "arch": data["context"]["arch"],
                "with_deps": data.get("with_deps", False),
                "downloaded_at": data.get("downloaded_at", ""),
                "artifact_root": data["artifact_root"],
                "manifest": str(manifest_path),
                "package_count": len(data.get("packages", [])),
            }
        )
    return sorted(
        packages,
        key=lambda item: (
            item["package_name"],
            item["package_version"],
            item["distro"],
            item["release"],
            item["arch"],
        ),
    )


def apt_policy_version(package_name: str) -> str:
    result = subprocess.run(
        ["apt-cache", "policy", package_name],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Candidate:"):
            candidate = stripped.split(":", 1)[1].strip()
            if candidate and candidate != "(none)":
                return candidate
            break
    raise ValueError(f"no apt candidate version found for package: {package_name}")


def apt_show_metadata(package_name: str, version: str) -> dict[str, str]:
    result = subprocess.run(
        ["apt-cache", "show", f"{package_name}={version}"],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key not in metadata:
            metadata[key] = value.strip()
    return metadata


def apt_dependency_names(package_name: str) -> list[str]:
    result = subprocess.run(
        [
            "apt-cache",
            "depends",
            "--recurse",
            "--no-recommends",
            "--no-suggests",
            "--no-conflicts",
            "--no-breaks",
            "--no-replaces",
            "--no-enhances",
            package_name,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    dependencies: list[str] = []
    seen: set[str] = set()
    for raw_line in result.stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("Depends:"):
            continue
        dep = stripped.split(":", 1)[1].strip()
        if not dep or dep.startswith("<"):
            continue
        dep = dep.split(" ", 1)[0]
        if dep == package_name or dep in seen:
            continue
        seen.add(dep)
        dependencies.append(dep)
    return dependencies


def apt_download_package(output_dir: Path, package_name: str, version: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    before = {path.name for path in output_dir.glob("*.deb")}
    subprocess.run(
        ["apt-get", "download", f"{package_name}={version}"],
        check=True,
        cwd=output_dir,
        capture_output=True,
        text=True,
    )
    after = list(output_dir.glob("*.deb"))
    created = [path for path in after if path.name not in before]
    if len(created) == 1:
        return created[0]
    matches = [path for path in after if path.name.startswith(f"{package_name}_")]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"unable to determine downloaded .deb for {package_name}={version}")
