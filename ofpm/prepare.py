from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ofpm.local_package import import_local_package
from ofpm.package_def import dump_package_file


FetchJson = Callable[[str], Any]
DownloadFile = Callable[[str, Path], None]
RunCommand = Callable[[list[str]], None]
Progress = Callable[[str], None]


@dataclass(frozen=True)
class PreparedPackage:
    package_id: str
    version: str
    package_root: Path
    repo_package_root: Path | None
    source: str
    sha256: str | None = None


@dataclass(frozen=True)
class PreparerInfo:
    id: str
    source: str
    output_package: str
    description: str


class Preparer(Protocol):
    info: PreparerInfo

    def list_versions(self, *, fetch_json: FetchJson | None = None) -> list[str]:
        ...

    def prepare(
        self,
        version: str,
        *,
        repo_dir: Path | None,
        work_dir: Path,
        replace: bool = False,
        fetch_json: FetchJson | None = None,
        download_file: DownloadFile | None = None,
        run_command: RunCommand | None = None,
        progress: Progress | None = None,
    ) -> PreparedPackage:
        ...


def default_fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "ofpm"})
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def default_download_file(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ofpm"})
    with urllib.request.urlopen(request) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output)


def default_run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def format_bytes(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def download_file_with_progress(url: str, path: Path, progress: Progress) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ofpm"})
    with urllib.request.urlopen(request) as response, path.open("wb") as output:
        total_header = response.headers.get("Content-Length", "").strip()
        total = int(total_header) if total_header.isdigit() else 0
        if total:
            progress(f"  download size: {format_bytes(total)}")
        downloaded = 0
        last_reported = 0
        last_time = time.monotonic()
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            now = time.monotonic()
            if downloaded - last_reported >= 64 * 1024 * 1024 or now - last_time >= 5:
                if total:
                    percent = downloaded * 100 / total
                    progress(f"  downloaded: {format_bytes(downloaded)} / {format_bytes(total)} ({percent:.1f}%)")
                else:
                    progress(f"  downloaded: {format_bytes(downloaded)}")
                last_reported = downloaded
                last_time = now
        if total:
            progress(f"  downloaded: {format_bytes(downloaded)} / {format_bytes(total)} (100.0%)")
        else:
            progress(f"  downloaded: {format_bytes(downloaded)}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_version(value: str) -> str:
    return value[1:] if value.startswith("v") else value


def version_sort_key(value: str) -> tuple:
    parts: list[object] = []
    for item in normalized_version(value).replace("-", ".").split("."):
        if item.isdigit():
            parts.append(int(item))
        else:
            parts.append(item)
    return tuple(parts)


def write_archive(source_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source_dir, arcname=source_dir.name)


def import_prepared_package(
    package_root: Path,
    *,
    repo_dir: Path | None,
    replace: bool,
) -> Path | None:
    if repo_dir is None:
        return None
    _, dest_root = import_local_package(repo_dir, package_root, replace=replace)
    return dest_root


class OllamaRuntimePreparer:
    info = PreparerInfo(
        id="ollama",
        source="github",
        output_package="ollama-runtime",
        description="Prepare an Ollama Linux runtime release archive",
    )

    releases_url = "https://api.github.com/repos/ollama/ollama/releases"

    def list_versions(self, *, fetch_json: FetchJson | None = None) -> list[str]:
        fetch = fetch_json or default_fetch_json
        releases = fetch(self.releases_url)
        versions = [
            normalized_version(item["tag_name"])
            for item in releases
            if not item.get("draft") and "tag_name" in item
        ]
        return sorted(set(versions), key=version_sort_key, reverse=True)

    def prepare(
        self,
        version: str,
        *,
        repo_dir: Path | None,
        work_dir: Path,
        replace: bool = False,
        fetch_json: FetchJson | None = None,
        download_file: DownloadFile | None = None,
        run_command: RunCommand | None = None,
        progress: Progress | None = None,
    ) -> PreparedPackage:
        log = progress or (lambda message: None)
        fetch = fetch_json or default_fetch_json
        download = download_file or (
            (lambda url, path: download_file_with_progress(url, path, log))
            if progress is not None
            else default_download_file
        )
        log(f"[ofpm] prepare ollama: resolving version {version}")
        resolved_version = self._resolve_version(version, fetch)
        log(f"[ofpm] prepare ollama: resolved version {resolved_version}")
        log("[ofpm] prepare ollama: reading release assets")
        release = fetch(f"https://api.github.com/repos/ollama/ollama/releases/tags/v{resolved_version}")
        asset = self._find_linux_amd64_asset(release)
        source_url = asset["browser_download_url"]
        archive_name = asset["name"]
        asset_size = asset.get("size")
        if isinstance(asset_size, int) and asset_size > 0:
            log(f"[ofpm] prepare ollama: selected asset {archive_name} ({format_bytes(asset_size)})")
        else:
            log(f"[ofpm] prepare ollama: selected asset {archive_name}")

        package_root = work_dir / self.info.output_package / resolved_version
        payload_root = package_root / "payload"
        archive_path = payload_root / archive_name
        if package_root.exists():
            log(f"[ofpm] prepare ollama: replacing staging directory {package_root}")
            shutil.rmtree(package_root)
        payload_root.mkdir(parents=True, exist_ok=True)
        log(f"[ofpm] prepare ollama: downloading archive")
        log(f"  url: {source_url}")
        log(f"  output: {archive_path}")
        download(source_url, archive_path)
        log("[ofpm] prepare ollama: hashing archive")
        digest = sha256_file(archive_path)

        log("[ofpm] prepare ollama: writing package recipe")
        dump_package_file(
            package_root / "package.py",
            {
                "schema_version": "1",
                "package_id": self.info.output_package,
                "version": resolved_version,
                "target": {"os": "linux", "distro": "", "release": "", "arch": "amd64"},
                "install_root": f"payloads/{self.info.output_package}/{resolved_version}",
                "depends": [],
                "plugins": [],
                "plugin_data": [],
                "metadata": {
                    "description": "Ollama runtime release prepared by ofpm",
                    "source_kind": "github-release",
                    "source_repo": "ollama/ollama",
                    "source_url": source_url,
                    "sha256": digest,
                    "install_mode": "archive",
                },
                "env": {
                    "prepend_path": {
                        "PATH": ["@package_root/bin"],
                        "LD_LIBRARY_PATH": ["@package_root/lib/ollama"],
                    },
                    "set": {"OLLAMA_LIBRARY_PATH": "@package_root/lib/ollama"},
                },
                "files": [{"source": f"payload/{archive_name}", "target": archive_name}],
            },
        )
        log("[ofpm] prepare ollama: importing package into repo" if repo_dir is not None else "[ofpm] prepare ollama: repo import skipped")
        dest_root = import_prepared_package(package_root, repo_dir=repo_dir, replace=replace)
        if dest_root is not None:
            log(f"[ofpm] prepare ollama: imported {dest_root}")
        return PreparedPackage(
            package_id=self.info.output_package,
            version=resolved_version,
            package_root=package_root,
            repo_package_root=dest_root,
            source=source_url,
            sha256=digest,
        )

    def _resolve_version(self, version: str, fetch: FetchJson) -> str:
        if version != "latest":
            return normalized_version(version)
        release = fetch("https://api.github.com/repos/ollama/ollama/releases/latest")
        return normalized_version(release["tag_name"])

    def _find_asset(self, release: dict[str, Any], name: str) -> dict[str, Any]:
        for asset in release.get("assets", []):
            if asset.get("name") == name:
                return asset
        raise ValueError(f"release asset not found: {name}")

    def _find_linux_amd64_asset(self, release: dict[str, Any]) -> dict[str, Any]:
        preferred_names = [
            "ollama-linux-amd64.tar.zst",
            "ollama-linux-amd64.tgz",
        ]
        assets = list(release.get("assets", []))
        for name in preferred_names:
            for asset in assets:
                if asset.get("name") == name:
                    return asset
        candidates = [
            asset
            for asset in assets
            if "linux-amd64" in str(asset.get("name", ""))
            and str(asset.get("name", "")).endswith((".tar.zst", ".tgz", ".tar.gz"))
            and "-rocm" not in str(asset.get("name", ""))
            and "-mlx" not in str(asset.get("name", ""))
        ]
        if len(candidates) == 1:
            return candidates[0]
        available = ", ".join(str(asset.get("name", "")) for asset in assets)
        raise ValueError(f"release linux amd64 archive asset not found; available assets: {available}")


class PiAgentPreparer:
    info = PreparerInfo(
        id="pi-agent",
        source="npm",
        output_package="pi-agent",
        description="Prepare Pi Coding Agent with npm dependency closure",
    )

    registry_url = "https://registry.npmjs.org/@earendil-works%2Fpi-coding-agent"
    package_name = "@earendil-works/pi-coding-agent"
    web_search_package_name = "@ollama/pi-web-search"

    def list_versions(self, *, fetch_json: FetchJson | None = None) -> list[str]:
        fetch = fetch_json or default_fetch_json
        data = fetch(self.registry_url)
        versions = list(data.get("versions", {}).keys())
        return sorted(set(versions), key=version_sort_key, reverse=True)

    def prepare(
        self,
        version: str,
        *,
        repo_dir: Path | None,
        work_dir: Path,
        replace: bool = False,
        fetch_json: FetchJson | None = None,
        download_file: DownloadFile | None = None,
        run_command: RunCommand | None = None,
        progress: Progress | None = None,
    ) -> PreparedPackage:
        log = progress or (lambda message: None)
        fetch = fetch_json or default_fetch_json
        runner = run_command or default_run_command
        log(f"[ofpm] prepare pi-agent: resolving version {version}")
        resolved_version = self._resolve_version(version, fetch)
        log(f"[ofpm] prepare pi-agent: resolved version {resolved_version}")
        package_root = work_dir / self.info.output_package / resolved_version
        payload_root = package_root / "payload"
        bundle_root = work_dir / "_pi-agent-bundle" / f"pi-agent-{resolved_version}"
        archive_path = payload_root / f"pi-agent-{resolved_version}.tar.gz"
        if package_root.exists():
            log(f"[ofpm] prepare pi-agent: replacing staging directory {package_root}")
            shutil.rmtree(package_root)
        if bundle_root.exists():
            shutil.rmtree(bundle_root)
        payload_root.mkdir(parents=True, exist_ok=True)
        bundle_root.mkdir(parents=True, exist_ok=True)

        install_root = bundle_root / "npm-prefix"
        log("[ofpm] prepare pi-agent: installing npm dependency closure")
        log(f"  prefix: {install_root}")
        runner(
            [
                "npm",
                "install",
                "--prefix",
                str(install_root),
                "--omit=dev",
                f"{self.package_name}@{resolved_version}",
                f"{self.web_search_package_name}@latest",
            ]
        )
        log("[ofpm] prepare pi-agent: writing launcher wrapper")
        self._write_pi_wrapper(bundle_root)
        log(f"[ofpm] prepare pi-agent: bundling archive {archive_path}")
        write_archive(bundle_root, archive_path)
        log("[ofpm] prepare pi-agent: hashing archive")
        digest = sha256_file(archive_path)

        log("[ofpm] prepare pi-agent: writing package recipe")
        dump_package_file(
            package_root / "package.py",
            {
                "schema_version": "1",
                "package_id": self.info.output_package,
                "version": resolved_version,
                "target": {"os": "linux", "distro": "", "release": "", "arch": "amd64"},
                "install_root": f"payloads/{self.info.output_package}/{resolved_version}",
                "depends": [{"package_id": "node"}],
                "plugins": [],
                "plugin_data": [],
                "metadata": {
                    "description": "Pi Coding Agent npm dependency closure prepared by ofpm",
                    "source_kind": "npm",
                    "source_package": self.package_name,
                    "source_version": resolved_version,
                    "included_packages": [self.package_name, self.web_search_package_name],
                    "sha256": digest,
                    "install_mode": "archive",
                },
                "env": {"prepend_path": {"PATH": ["@package_root/bin"]}},
                "files": [{"source": f"payload/{archive_path.name}", "target": archive_path.name}],
            },
        )
        log("[ofpm] prepare pi-agent: importing package into repo" if repo_dir is not None else "[ofpm] prepare pi-agent: repo import skipped")
        dest_root = import_prepared_package(package_root, repo_dir=repo_dir, replace=replace)
        if dest_root is not None:
            log(f"[ofpm] prepare pi-agent: imported {dest_root}")
        return PreparedPackage(
            package_id=self.info.output_package,
            version=resolved_version,
            package_root=package_root,
            repo_package_root=dest_root,
            source=f"{self.package_name}@{resolved_version}",
            sha256=digest,
        )

    def _resolve_version(self, version: str, fetch: FetchJson) -> str:
        data = fetch(self.registry_url)
        if version == "latest":
            return data["dist-tags"]["latest"]
        if version not in data.get("versions", {}):
            raise ValueError(f"npm package version not found: {self.package_name}@{version}")
        return version

    def _write_pi_wrapper(self, bundle_root: Path) -> None:
        bin_dir = bundle_root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        wrapper = bin_dir / "pi"
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'PREFIX="$(cd "$SCRIPT_DIR/../npm-prefix" && pwd)"\n'
            'exec node "$PREFIX/node_modules/@earendil-works/pi-coding-agent/dist/cli.js" "$@"\n',
            encoding="utf-8",
        )
        os.chmod(wrapper, 0o755)


PREPARERS: dict[str, Preparer] = {
    "ollama": OllamaRuntimePreparer(),
    "pi-agent": PiAgentPreparer(),
}


def list_preparers() -> list[PreparerInfo]:
    return [preparer.info for preparer in PREPARERS.values()]


def get_preparer(preparer_id: str) -> Preparer:
    normalized = preparer_id.strip().lower()
    try:
        return PREPARERS[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown preparer: {preparer_id}") from exc


def prepare_package(
    preparer_id: str,
    version: str,
    *,
    repo_dir: Path | None,
    work_dir: Path | None = None,
    replace: bool = False,
    progress: Progress | None = None,
) -> PreparedPackage:
    preparer = get_preparer(preparer_id)
    if work_dir is not None:
        work_root = work_dir.expanduser().resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        return preparer.prepare(version, repo_dir=repo_dir, work_dir=work_root, replace=replace, progress=progress)
    with tempfile.TemporaryDirectory(prefix="ofpm-prepare-") as temp_dir:
        return preparer.prepare(version, repo_dir=repo_dir, work_dir=Path(temp_dir), replace=replace, progress=progress)
