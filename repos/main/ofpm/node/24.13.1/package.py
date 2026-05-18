from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

from ofpm.recipes import OfpmRecipe
from ofpm.runtime_support import (
    detect_single_subdir,
    expanded_package_entries,
    record_install,
    remove_managed_payload,
    reset_current_link,
    sha256_file,
    utc_now,
    verify_node_runtime_install,
)


class Recipe(OfpmRecipe):
    def __init__(self):
        super().__init__(
            package_id="node",
            version="24.13.1",
            target={"os": "linux", "distro": "ubuntu", "release": "22.04", "arch": "amd64"},
            install_root="payloads/node/24.13.1",
            depends=[],
            metadata={
                "description": "offline node runtime archive stored inside repos/main",
                "source_kind": "repo-internal",
                "origin_relroot": "packages/node/24.13.1/payload",
            },
            env={"prepend_path": {"PATH": ["@package_root/bin"]}},
            files=[
                {
                    "source": "payload/node-v24.13.1-linux-x64.tar.xz",
                    "target": "node-v24.13.1-linux-x64.tar.xz",
                    "mode": "0644",
                }
            ],
        )

    def install(self, runtime):
        package_data = runtime.package_data
        package_id = package_data["package_id"]
        version = package_data["version"]
        version_root = runtime.managed_root / "payloads" / package_id / version
        artifacts_root = version_root / "artifacts"
        if version_root.exists():
            raise FileExistsError(f"package version already installed at {version_root}")

        runtime.managed_root.mkdir(parents=True, exist_ok=True)
        artifacts_root.mkdir(parents=True, exist_ok=False)

        entries = expanded_package_entries(package_data, runtime.package_manifest, artifact_roots=runtime.artifact_roots)
        if len(entries) != 1:
            raise ValueError("node install expects exactly one source artifact")

        tarball_source = Path(entries[0]["source"]).resolve()
        tarball_dest = artifacts_root / tarball_source.name
        shutil.copy2(tarball_source, tarball_dest)
        with tarfile.open(tarball_dest, "r:xz") as tar:
            tar.extractall(version_root)

        extracted_root = detect_single_subdir(version_root, exclude_names={"artifacts"})
        current_link = runtime.managed_root / "payloads" / package_id / "current"
        reset_current_link(current_link, extracted_root)

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
        record_install(
            runtime.managed_root,
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
        return state

    def verify(self, runtime):
        return verify_node_runtime_install(runtime.installed_state or {})

    def remove(self, runtime):
        return remove_managed_payload(runtime.managed_root, runtime.installed_state or {})


RECIPE = Recipe()
