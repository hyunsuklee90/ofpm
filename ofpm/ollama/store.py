from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REGISTRY = "registry.ollama.ai"
DEFAULT_NAMESPACE = "library"
DEFAULT_TAG = "latest"


@dataclass(frozen=True)
class OllamaModel:
    ref: str
    full_ref: str
    manifest_path: Path
    manifest_relpath: Path
    digests: tuple[str, ...]
    total_blob_size: int
    missing_blobs: tuple[str, ...]


def default_models_dir() -> Path:
    configured = os.environ.get("OLLAMA_MODELS", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".ollama" / "models").resolve()


def manifests_dir(models_dir: Path) -> Path:
    return models_dir / "manifests"


def blobs_dir(models_dir: Path) -> Path:
    return models_dir / "blobs"


def normalize_digest(digest: str) -> str:
    value = digest.strip()
    if value.startswith("sha256:"):
        value = value[len("sha256:") :]
    elif value.startswith("sha256-"):
        value = value[len("sha256-") :]
    if not value:
        raise ValueError("empty sha256 digest")
    if any(char not in "0123456789abcdefABCDEF" for char in value):
        raise ValueError(f"unsupported sha256 digest: {digest}")
    if len(value) != 64:
        raise ValueError(f"unsupported sha256 digest length: {digest}")
    return value.lower()


def blob_path(models_dir: Path, digest: str) -> Path:
    return blobs_dir(models_dir) / f"sha256-{normalize_digest(digest)}"


def digest_from_blob_name(path: Path) -> str:
    name = path.name
    if not name.startswith("sha256-"):
        raise ValueError(f"unsupported ollama blob name: {name}")
    return normalize_digest(name)


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid ollama manifest JSON: {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"ollama manifest is not a JSON object: {manifest_path}")
    return data


def manifest_digests(manifest: dict[str, Any]) -> tuple[str, ...]:
    digests: list[str] = []
    config = manifest.get("config")
    if isinstance(config, dict) and isinstance(config.get("digest"), str):
        digests.append(normalize_digest(config["digest"]))
    layers = manifest.get("layers", [])
    if isinstance(layers, list):
        for layer in layers:
            if isinstance(layer, dict) and isinstance(layer.get("digest"), str):
                digests.append(normalize_digest(layer["digest"]))
    return tuple(dict.fromkeys(digests))


def display_ref_from_manifest_relpath(relpath: Path) -> str:
    parts = relpath.parts
    if len(parts) < 3:
        return relpath.as_posix()
    registry = parts[0]
    tag = parts[-1]
    name_parts = parts[1:-1]
    if registry == DEFAULT_REGISTRY and len(name_parts) == 2 and name_parts[0] == DEFAULT_NAMESPACE:
        return f"{name_parts[1]}:{tag}"
    return f"{'/'.join((registry, *name_parts))}:{tag}"


def full_ref_from_manifest_relpath(relpath: Path) -> str:
    parts = relpath.parts
    if len(parts) < 3:
        return relpath.as_posix()
    return f"{'/'.join(parts[:-1])}:{parts[-1]}"


def candidate_manifest_relpaths(model_ref: str) -> list[Path]:
    value = model_ref.strip()
    if not value:
        raise ValueError("model ref is required")
    if ":" in value:
        name, tag = value.rsplit(":", 1)
    else:
        name, tag = value, DEFAULT_TAG
    name_parts = [part for part in name.split("/") if part]
    if not name_parts:
        raise ValueError(f"invalid model ref: {model_ref}")
    candidates: list[Path] = []
    if len(name_parts) == 1:
        candidates.append(Path(DEFAULT_REGISTRY) / DEFAULT_NAMESPACE / name_parts[0] / tag)
    elif len(name_parts) == 2:
        candidates.append(Path(DEFAULT_REGISTRY) / name_parts[0] / name_parts[1] / tag)
    else:
        candidates.append(Path(*name_parts) / tag)
    return candidates


def iter_manifest_paths(models_dir: Path) -> list[Path]:
    root = manifests_dir(models_dir)
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def inspect_model(models_dir: Path, manifest_path: Path) -> OllamaModel:
    manifest_root = manifests_dir(models_dir)
    relpath = manifest_path.relative_to(manifest_root)
    manifest = load_manifest(manifest_path)
    digests = manifest_digests(manifest)
    missing: list[str] = []
    size = 0
    for digest in digests:
        path = blob_path(models_dir, digest)
        if path.exists():
            size += path.stat().st_size
        else:
            missing.append(digest)
    return OllamaModel(
        ref=display_ref_from_manifest_relpath(relpath),
        full_ref=full_ref_from_manifest_relpath(relpath),
        manifest_path=manifest_path,
        manifest_relpath=relpath,
        digests=digests,
        total_blob_size=size,
        missing_blobs=tuple(missing),
    )


def list_models(models_dir: Path) -> list[OllamaModel]:
    return [inspect_model(models_dir, path) for path in iter_manifest_paths(models_dir)]


def resolve_model(models_dir: Path, model_ref: str) -> OllamaModel:
    manifest_root = manifests_dir(models_dir)
    for relpath in candidate_manifest_relpaths(model_ref):
        candidate = manifest_root / relpath
        if candidate.is_file():
            return inspect_model(models_dir, candidate)

    matches = [
        model
        for model in list_models(models_dir)
        if model.ref == model_ref or model.full_ref == model_ref or model.manifest_relpath.as_posix() == model_ref
    ]
    if not matches:
        raise ValueError(f"ollama model not found in {models_dir}: {model_ref}")
    if len(matches) > 1:
        refs = ", ".join(sorted(model.full_ref for model in matches))
        raise ValueError(f"ambiguous ollama model ref: {model_ref} ({refs})")
    return matches[0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
