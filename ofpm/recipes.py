from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseRecipe(ABC):
    def __init__(
        self,
        *,
        package_id: str,
        version: str,
        target: dict[str, Any] | None = None,
        install_root: str,
        depends: list[dict[str, Any]] | None = None,
        plugins: list[dict[str, Any]] | None = None,
        plugin_data: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        env: dict[str, Any] | None = None,
        files: list[dict[str, Any]] | None = None,
        provider: str,
        schema_version: str = "1",
    ) -> None:
        self.package_id = package_id
        self.version = version
        self.target = dict(target or {})
        self.install_root = install_root
        self.depends = list(depends or [])
        self.plugins = list(plugins or [])
        self.plugin_data = list(plugin_data or [])
        self.metadata = dict(metadata or {})
        self.env = dict(env or {})
        self.files = list(files or [])
        self.provider = provider
        self.schema_version = schema_version

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "version": self.version,
            "target": dict(self.target),
            "install_root": self.install_root,
            "depends": list(self.depends),
            "plugins": list(self.plugins),
            "plugin_data": list(self.plugin_data),
            "metadata": {
                **self.metadata,
                "provider": self.provider,
            },
            "env": dict(self.env),
            "files": list(self.files),
        }

    @abstractmethod
    def install(self, runtime):
        raise NotImplementedError

    @abstractmethod
    def verify(self, runtime):
        raise NotImplementedError

    @abstractmethod
    def remove(self, runtime):
        raise NotImplementedError


class OfpmRecipe(BaseRecipe):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(provider="ofpm", **kwargs)


class AptRecipe(BaseRecipe):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(provider="apt", **kwargs)


class OfpmManagedFilesRecipe(OfpmRecipe):
    def install(self, runtime):
        return runtime.install_managed_files()

    def verify(self, runtime):
        return runtime.verify_managed_files()

    def remove(self, runtime):
        return runtime.remove_managed_payload()


class OfpmArchiveExtractRecipe(OfpmRecipe):
    def install(self, runtime):
        return runtime.install_archive_extract()

    def verify(self, runtime):
        return runtime.verify_managed_files()

    def remove(self, runtime):
        return runtime.remove_managed_payload()


class AptManagedFilesRecipe(AptRecipe):
    def install(self, runtime):
        return runtime.install_managed_files()

    def verify(self, runtime):
        return runtime.verify_managed_files()

    def remove(self, runtime):
        return runtime.remove_managed_payload()
