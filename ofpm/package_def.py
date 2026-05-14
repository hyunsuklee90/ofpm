from __future__ import annotations

import importlib.util
import json
import pprint
from pathlib import Path
from typing import Any


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


def load_package_file(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        return normalize_package_data(json.loads(path.read_text(encoding="utf-8")))
    if path.suffix != ".py":
        raise ValueError(f"unsupported package definition: {path}")

    spec = importlib.util.spec_from_file_location(f"ofpm_package_{path.stem}_{abs(hash(path))}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load package definition: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    package_fn = getattr(module, "package", None)
    if package_fn is None:
        raise ValueError(f"package definition missing package() function: {path}")
    data = package_fn()
    if not isinstance(data, dict):
        raise ValueError(f"package() must return a dict: {path}")
    return normalize_package_data(data)


def dump_package_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = pprint.pformat(normalize_package_data(data), sort_dicts=False, width=100)
    path.write_text(
        "from __future__ import annotations\n\n\n"
        "def package():\n"
        f"    return {body}\n",
        encoding="utf-8",
    )
