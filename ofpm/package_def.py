from __future__ import annotations

import importlib.util
import json
import pprint
from functools import lru_cache
from pathlib import Path
from typing import Any

from ofpm.recipes import BaseRecipe


def normalize_package_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    target = normalized.get("target")
    if target is None:
        profile_id = normalized.get("profile_id")
        if profile_id:
            distro, _, release = profile_id.partition("-")
            normalized["target"] = {
                "os": "linux",
                "distro": distro,
                "release": release,
                "arch": "amd64",
            }
    elif "profile_id" not in normalized:
        distro = target.get("distro", "")
        release = target.get("release", "")
        if distro and release:
            normalized["profile_id"] = f"{distro}-{release}"
        else:
            normalized["profile_id"] = "generic"
    return normalized


@lru_cache(maxsize=256)
def load_package_module(path: str):
    package_path = Path(path)
    if package_path.suffix != ".py":
        return None
    spec = importlib.util.spec_from_file_location(
        f"ofpm_package_{package_path.stem}_{abs(hash(package_path))}",
        package_path,
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load package definition: {package_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_package_file(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        return normalize_package_data(json.loads(path.read_text(encoding="utf-8")))
    if path.suffix != ".py":
        raise ValueError(f"unsupported package definition: {path}")

    recipe = load_package_recipe(path)
    if recipe is not None:
        return normalize_package_data(recipe.manifest())

    module = load_package_module(str(path))
    package_fn = getattr(module, "package", None)
    if package_fn is None:
        raise ValueError(f"package definition missing recipe or package() function: {path}")
    data = package_fn()
    if not isinstance(data, dict):
        raise ValueError(f"package() must return a dict: {path}")
    return normalize_package_data(data)


def load_package_recipe(path: Path) -> BaseRecipe | None:
    if path.suffix != ".py":
        return None
    module = load_package_module(str(path))

    recipe = getattr(module, "RECIPE", None)
    if isinstance(recipe, BaseRecipe):
        return recipe

    recipe_cls = getattr(module, "Recipe", None)
    if isinstance(recipe_cls, type) and issubclass(recipe_cls, BaseRecipe):
        return recipe_cls()
    return None


def load_package_hook(path: Path, hook_name: str):
    if path.suffix != ".py":
        return None
    recipe = load_package_recipe(path)
    if recipe is not None:
        hook = getattr(recipe, hook_name, None)
        if hook is not None and callable(hook):
            return hook
    module = load_package_module(str(path))
    hook = getattr(module, hook_name, None)
    if hook is None or not callable(hook):
        return None
    return hook


def dump_package_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_package_data(data)
    is_installable_recipe = all(key in normalized for key in ["package_id", "version", "install_root", "files"])
    if not is_installable_recipe:
        body = pprint.pformat(normalized, sort_dicts=False, width=100)
        path.write_text(
            "from __future__ import annotations\n\n\n"
            "def package():\n"
            f"    return {body}\n",
            encoding="utf-8",
        )
        return

    provider = normalized.get("metadata", {}).get("provider", "ofpm")
    schema_version = normalized.get("schema_version", "1")
    base_class = "AptManagedFilesRecipe" if provider == "apt" else "OfpmManagedFilesRecipe"
    body_target = pprint.pformat(normalized.get("target", {}), sort_dicts=False, width=100)
    body_depends = pprint.pformat(normalized.get("depends", []), sort_dicts=False, width=100)
    body_plugins = pprint.pformat(normalized.get("plugins", []), sort_dicts=False, width=100)
    body_plugin_data = pprint.pformat(normalized.get("plugin_data", []), sort_dicts=False, width=100)
    body_metadata = pprint.pformat(normalized.get("metadata", {}), sort_dicts=False, width=100)
    body_env = pprint.pformat(normalized.get("env", {}), sort_dicts=False, width=100)
    body_files = pprint.pformat(normalized.get("files", []), sort_dicts=False, width=100)
    path.write_text(
        "from __future__ import annotations\n\n"
        f"from ofpm.recipes import {base_class}\n\n\n"
        f"class Recipe({base_class}):\n"
        "    def __init__(self):\n"
        "        super().__init__(\n"
        f"            package_id={normalized['package_id']!r},\n"
        f"            version={normalized['version']!r},\n"
        f"            target={body_target},\n"
        f"            install_root={normalized['install_root']!r},\n"
        f"            depends={body_depends},\n"
        f"            plugins={body_plugins},\n"
        f"            plugin_data={body_plugin_data},\n"
        f"            metadata={body_metadata},\n"
        f"            env={body_env},\n"
        f"            files={body_files},\n"
        f"            schema_version={schema_version!r},\n"
        "        )\n\n\n"
        "RECIPE = Recipe()\n",
        encoding="utf-8",
    )
