from __future__ import annotations

import os
import shutil
import subprocess

from ofpm.process_ui import run_command_live
from ofpm.recipes import OfpmRecipe
from ofpm.runtime_support import (
    expose_public_executables,
    package_files_by_target,
    record_install,
    remove_managed_payload,
    reset_current_link,
    utc_now,
    verify_ollama_runtime_install,
)


class Recipe(OfpmRecipe):
    def __init__(self):
        super().__init__(
            package_id="ollama",
            version="0.23.2",
            target={"os": "linux", "distro": "ubuntu", "release": "22.04", "arch": "amd64"},
            install_root="payloads/ollama/0.23.2",
            depends=[],
            metadata={
                "description": "offline ollama runtime artifacts stored inside repos/main",
                "source_kind": "repo-internal",
                "origin_relroot": "packages/ollama/0.23.2/payload",
            },
            env={
                "set": {"OLLAMA_LIBRARY_PATH": "@library_dir"},
                "prepend_path": {
                    "PATH": ["@package_root/bin"],
                    "LD_LIBRARY_PATH": ["@library_dir"],
                },
            },
            files=[
                {
                    "source": "payload/archives/ollama-linux-amd64.tar.gz",
                    "target": "archives/ollama-linux-amd64.tar.gz",
                    "mode": "0644",
                },
                {
                    "source": "payload/archives/ollama-linux-amd64.tar.zst",
                    "target": "archives/ollama-linux-amd64.tar.zst",
                    "mode": "0644",
                }
            ],
        )

    def install(self, runtime):
        package_data = runtime.package_data
        package_id = package_data["package_id"]
        version = package_data["version"]
        version_root = runtime.managed_root / "payloads" / package_id / version
        if version_root.exists():
            raise FileExistsError(f"package version already installed at {version_root}")

        runtime.managed_root.mkdir(parents=True, exist_ok=True)
        version_root.mkdir(parents=True, exist_ok=False)

        files = package_files_by_target(package_data, runtime.package_manifest, artifact_roots=runtime.artifact_roots)
        archive_gz = files.get("archives/ollama-linux-amd64.tar.gz")
        archive_zst = files.get("archives/ollama-linux-amd64.tar.zst")
        binary_source = files.get("bin/ollama")

        install_mode = "archive"
        if archive_gz and archive_gz.exists():
            try:
                run_command_live(
                    ["tar", "-xzf", str(archive_gz), "-C", str(version_root)],
                    label="extract ollama archive",
                )
            except subprocess.CalledProcessError:
                shutil.rmtree(version_root, ignore_errors=True)
                version_root.mkdir(parents=True, exist_ok=False)
                if archive_zst and archive_zst.exists() and shutil.which("zstd"):
                    run_command_live(
                        ["tar", "--zstd", "-xf", str(archive_zst), "-C", str(version_root)],
                        label="extract ollama archive",
                    )
                else:
                    raise ValueError(
                        "ollama runtime tar.gz archive is incomplete or corrupted; "
                        "regenerate payload/archives/ollama-linux-amd64.tar.gz"
                    )
        elif archive_zst and archive_zst.exists() and shutil.which("zstd"):
            run_command_live(
                ["tar", "--zstd", "-xf", str(archive_zst), "-C", str(version_root)],
                label="extract ollama archive",
            )
        elif binary_source and binary_source.exists():
            install_mode = "binary-only"
            (version_root / "bin").mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary_source, version_root / "bin" / "ollama")
            os.chmod(version_root / "bin" / "ollama", 0o755)
        else:
            raise FileNotFoundError("missing ollama runtime archive and raw binary")

        current_link = runtime.managed_root / "payloads" / package_id / "current"
        reset_current_link(current_link, version_root)
        library_dir = current_link / "lib" / "ollama"
        executables = [str(current_link / "bin" / "ollama")]
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
                "executables": executables,
                "public_executables": public_executables,
                "library_dir": str(library_dir),
                "install_mode": install_mode,
                "source_artifacts": [
                    str(path) for path in [archive_gz, archive_zst, binary_source] if path is not None and path.exists()
                ],
            },
        }
        record_install(
            runtime.managed_root,
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
        return state

    def verify(self, runtime):
        return verify_ollama_runtime_install(runtime.installed_state or {})

    def remove(self, runtime):
        return remove_managed_payload(runtime.managed_root, runtime.installed_state or {})


RECIPE = Recipe()
