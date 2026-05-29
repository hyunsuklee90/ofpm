from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofpm.package_def import load_package_hook
from ofpm.runtime_support import install_managed_files_package, remove_managed_payload, verify_managed_files_install


@dataclass
class PackageRuntimeContext:
    managed_root: Path
    package_manifest: Path
    package_data: dict[str, Any]
    root_kind: str
    artifact_roots: dict[str, str] | None = None
    installed_state: dict[str, Any] | None = None
    strict_modes: bool = False
    target_root: Path | None = None

    def install_managed_files(self) -> dict[str, Any]:
        return install_managed_files_package(
            self.managed_root,
            self.package_manifest,
            self.package_data,
            root_kind=self.root_kind,
            artifact_roots=self.artifact_roots,
        )

    def install_archive_extract(self) -> dict[str, Any]:
        from ofpm.runtime_support import install_archive_extract_package

        return install_archive_extract_package(
            self.managed_root,
            self.package_manifest,
            self.package_data,
            root_kind=self.root_kind,
            artifact_roots=self.artifact_roots,
        )

    def remove_managed_payload(self) -> dict[str, Any]:
        return remove_managed_payload(
            self.managed_root,
            self.installed_state or {},
        )

    def verify_managed_files(self) -> list[str]:
        return verify_managed_files_install(self.installed_state or {})


def install_package_from_definition(
    managed_root: Path,
    package_manifest: Path,
    package_data: dict[str, Any],
    *,
    root_kind: str,
    artifact_roots: dict[str, str] | None = None,
) -> dict[str, Any]:
    ctx = PackageRuntimeContext(
        managed_root=managed_root,
        package_manifest=package_manifest,
        package_data=package_data,
        root_kind=root_kind,
        artifact_roots=artifact_roots,
    )
    hook = load_package_hook(package_manifest, "install")
    if hook is not None:
        return hook(ctx)
    return ctx.install_managed_files()


def verify_package_from_definition(
    managed_root: Path,
    package_manifest: Path,
    package_data: dict[str, Any],
    installed_state: dict[str, Any],
    *,
    root_kind: str,
    strict_modes: bool = False,
    target_root: Path | None = None,
) -> list[str] | None:
    ctx = PackageRuntimeContext(
        managed_root=managed_root,
        package_manifest=package_manifest,
        package_data=package_data,
        root_kind=root_kind,
        installed_state=installed_state,
        strict_modes=strict_modes,
        target_root=target_root,
    )
    hook = load_package_hook(package_manifest, "verify")
    if hook is None:
        return None
    return hook(ctx)


def remove_package_from_definition(
    managed_root: Path,
    package_manifest: Path,
    package_data: dict[str, Any],
    installed_state: dict[str, Any],
    *,
    root_kind: str,
) -> dict[str, Any] | None:
    ctx = PackageRuntimeContext(
        managed_root=managed_root,
        package_manifest=package_manifest,
        package_data=package_data,
        root_kind=root_kind,
        installed_state=installed_state,
    )
    hook = load_package_hook(package_manifest, "remove")
    if hook is None:
        return None
    return hook(ctx)
