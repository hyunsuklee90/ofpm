from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def managed_state_root(managed_root: Path) -> Path:
    return managed_root / "state"


def managed_installed_state_root(managed_root: Path) -> Path:
    return managed_state_root(managed_root) / "installed"


def managed_receipts_root(managed_root: Path) -> Path:
    return managed_state_root(managed_root) / "receipts"


def managed_ownership_root(managed_root: Path) -> Path:
    return managed_state_root(managed_root) / "ownership"


def managed_history_path(managed_root: Path) -> Path:
    return managed_state_root(managed_root) / "history.json"


def managed_plugins_path(managed_root: Path) -> Path:
    return managed_state_root(managed_root) / "plugins.json"


def managed_state_file(managed_root: Path, package_id: str) -> Path:
    return managed_installed_state_root(managed_root) / f"{package_id}.json"


def managed_receipt_file(managed_root: Path, package_id: str) -> Path:
    return managed_receipts_root(managed_root) / f"{package_id}.json"


def ownership_entry_path(managed_root: Path, kind: str, name: str) -> Path:
    safe_kind = kind.replace("/", "-")
    safe_name = name.replace("/", "-")
    return managed_ownership_root(managed_root) / safe_kind / f"{safe_name}.json"


def load_history(managed_root: Path) -> dict[str, Any]:
    path = managed_history_path(managed_root)
    if not path.exists():
        return {"schema_version": "1", "events": []}
    return load_json(path)


def load_plugins_state(managed_root: Path) -> dict[str, Any]:
    path = managed_plugins_path(managed_root)
    if not path.exists():
        return {"schema_version": "1", "hosts": {}}
    return load_json(path)


def save_plugins_state(managed_root: Path, data: dict[str, Any]) -> None:
    dump_json(managed_plugins_path(managed_root), data)


def append_history_event(managed_root: Path, event: dict[str, Any]) -> None:
    history = load_history(managed_root)
    history.setdefault("events", []).append(event)
    dump_json(managed_history_path(managed_root), history)


def list_receipts(managed_root: Path) -> list[dict[str, Any]]:
    root = managed_receipts_root(managed_root)
    if not root.exists():
        return []
    receipts: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        data = load_json(path)
        data["receipt_path"] = str(path)
        receipts.append(data)
    return receipts


def list_ownership_entries(managed_root: Path) -> list[dict[str, Any]]:
    root = managed_ownership_root(managed_root)
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/*.json")):
        data = load_json(path)
        data["ownership_path"] = str(path)
        entries.append(data)
    return entries


def build_install_receipt(
    state: dict[str, Any],
    *,
    provider: str,
    strategy: str,
    claims: list[dict[str, str]] | None = None,
    source_repo: dict[str, str] | None = None,
    artifact_ref: dict[str, Any] | None = None,
    managed_objects: dict[str, Any] | None = None,
) -> dict[str, Any]:
    package = state["package"]
    package_id = package["package_id"]
    receipt_claims = claims or [{"kind": "package", "name": package_id}]
    return {
        "schema_version": "1",
        "receipt_id": package_id,
        "package_id": package_id,
        "package_version": package["package_version"],
        "provider": provider,
        "strategy": strategy,
        "root_kind": state.get("root_kind", ""),
        "managed_root": state.get("managed_root", ""),
        "installed_at": state.get("updated_at", utc_now()),
        "state_path": state.get("_state_path", ""),
        "source_repo": source_repo or {},
        "artifact_ref": artifact_ref or {},
        "claims": receipt_claims,
        "managed_objects": managed_objects or {},
    }


def update_ownership_for_install(managed_root: Path, receipt: dict[str, Any]) -> None:
    owner = {
        "package_id": receipt["package_id"],
        "package_version": receipt["package_version"],
        "provider": receipt["provider"],
        "strategy": receipt["strategy"],
        "receipt_id": receipt["receipt_id"],
    }
    for claim in receipt.get("claims", []):
        path = ownership_entry_path(managed_root, claim["kind"], claim["name"])
        if path.exists():
            entry = load_json(path)
        else:
            entry = {
                "schema_version": "1",
                "kind": claim["kind"],
                "name": claim["name"],
                "owners": [],
            }
        owners = [item for item in entry.get("owners", []) if item.get("receipt_id") != owner["receipt_id"]]
        owners.append(owner)
        entry["owners"] = sorted(owners, key=lambda item: (item["package_id"], item["package_version"]))
        entry["updated_at"] = utc_now()
        dump_json(path, entry)


def remove_ownership_for_receipt(managed_root: Path, receipt: dict[str, Any]) -> None:
    for claim in receipt.get("claims", []):
        path = ownership_entry_path(managed_root, claim["kind"], claim["name"])
        if not path.exists():
            continue
        entry = load_json(path)
        owners = [
            item
            for item in entry.get("owners", [])
            if item.get("receipt_id") != receipt["receipt_id"]
        ]
        if owners:
            entry["owners"] = owners
            entry["updated_at"] = utc_now()
            dump_json(path, entry)
            continue
        path.unlink()
        parent = path.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


def record_install(
    managed_root: Path,
    state: dict[str, Any],
    *,
    provider: str,
    strategy: str,
    claims: list[dict[str, str]] | None = None,
    source_repo: dict[str, str] | None = None,
    artifact_ref: dict[str, Any] | None = None,
    managed_objects: dict[str, Any] | None = None,
    write_history: bool = True,
    write_state: bool = True,
) -> dict[str, Any]:
    package_id = state["package"]["package_id"]
    state_path = managed_state_file(managed_root, package_id)
    state["_state_path"] = str(state_path)
    if write_state:
        dump_json(state_path, state)
    receipt = build_install_receipt(
        state,
        provider=provider,
        strategy=strategy,
        claims=claims,
        source_repo=source_repo,
        artifact_ref=artifact_ref,
        managed_objects=managed_objects,
    )
    dump_json(managed_receipt_file(managed_root, package_id), receipt)
    update_ownership_for_install(managed_root, receipt)
    if write_history:
        append_history_event(
            managed_root,
            {
                "timestamp": utc_now(),
                "action": "install",
                "package_id": receipt["package_id"],
                "package_version": receipt["package_version"],
                "provider": receipt["provider"],
                "strategy": receipt["strategy"],
                "receipt_id": receipt["receipt_id"],
            },
        )
    return receipt


def record_removal(managed_root: Path, installed_state: dict[str, Any]) -> None:
    package = installed_state["raw"]["package"]
    package_id = package["package_id"]
    receipt_path = managed_receipt_file(managed_root, package_id)
    receipt = load_json(receipt_path) if receipt_path.exists() else {
        "receipt_id": package_id,
        "package_id": package_id,
        "package_version": package.get("package_version", ""),
        "provider": "unknown",
        "strategy": "unknown",
        "claims": [{"kind": "package", "name": package_id}],
    }
    remove_ownership_for_receipt(managed_root, receipt)
    append_history_event(
        managed_root,
        {
            "timestamp": utc_now(),
            "action": "remove",
            "package_id": receipt["package_id"],
            "package_version": receipt["package_version"],
            "provider": receipt["provider"],
            "strategy": receipt["strategy"],
            "receipt_id": receipt["receipt_id"],
        },
    )
    state_path = managed_state_file(managed_root, package_id)
    if state_path.exists():
        state_path.unlink()
    if receipt_path.exists():
        receipt_path.unlink()
