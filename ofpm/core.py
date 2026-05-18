from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ofpm.repo_data import installed_states, managed_state_root
from ofpm.state_db import managed_receipt_file, record_install


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inferred_receipt_metadata(installed_state: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    package = installed_state["raw"]["package"]
    managed_objects: dict[str, Any] = {
        "version_root": package.get("version_root", ""),
        "current_path": package.get("current_path", ""),
        "executables": package.get("executables", []),
    }
    if "prefix_root" in package:
        managed_objects["prefix_root"] = package["prefix_root"]
    if "config_dir" in package:
        managed_objects["config_dir"] = package["config_dir"]
    if "library_dir" in package:
        managed_objects["library_dir"] = package["library_dir"]
    if "models_path" in package:
        managed_objects["models_path"] = package["models_path"]

    artifact_ref: dict[str, Any] = {}
    if "artifacts" in package:
        artifact_ref = {"type": "stored-artifact", "paths": package["artifacts"]}
    elif "source_artifacts" in package:
        artifact_ref = {"type": "source-artifacts", "paths": package["source_artifacts"]}

    package_id = installed_state["package_id"]
    if package_id in {"node", "node-runtime"}:
        return "ofpm-native", "archive-extract", managed_objects, artifact_ref
    if package_id in {"ollama", "ollama-runtime"}:
        return "ofpm-native", "managed-runtime", managed_objects, artifact_ref
    if package_id == "pi-agent":
        return "ofpm-native", "offline-npm-prefix", managed_objects, artifact_ref
    if package_id.startswith("ollama-model-"):
        return "ofpm-native", "managed-model-store", managed_objects, artifact_ref
    return "ofpm-native", "legacy-state-import", managed_objects, artifact_ref


def sync_managed_state_db(managed_root: Path) -> dict[str, int]:
    installed = installed_states(managed_state_root(managed_root))
    created = 0
    failed = 0
    for item in installed:
        receipt_path = managed_receipt_file(managed_root, item["package_id"])
        if receipt_path.exists():
            continue
        provider, strategy, managed_objects, artifact_ref = inferred_receipt_metadata(item)
        try:
            record_install(
                managed_root,
                item["raw"],
                provider=provider,
                strategy=strategy,
                managed_objects=managed_objects,
                artifact_ref=artifact_ref,
                write_history=False,
                write_state=False,
            )
            created += 1
        except OSError:
            failed += 1
    return {"installed_count": len(installed), "created_receipts": created, "failed_receipts": failed}


def verify_state(target_root: Path, state_path: Path, *, check_modes: bool = False) -> list[str]:
    state = load_json(state_path)
    errors: list[str] = []
    for tracked in state["package"]["tracked_files"]:
        install_path = target_root / tracked["install_path"]
        if not install_path.exists():
            errors.append(f"missing file: {tracked['install_path']}")
            continue
        actual_hash = sha256_file(install_path)
        if actual_hash != tracked["sha256"]:
            errors.append(f"hash mismatch: {tracked['install_path']}")
        if check_modes:
            actual_mode = format(install_path.stat().st_mode & 0o777, "04o")
            if actual_mode != tracked["mode"]:
                errors.append(
                    f"mode mismatch: {tracked['install_path']} expected={tracked['mode']} actual={actual_mode}"
                )
    return errors
