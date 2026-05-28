from __future__ import annotations

import filecmp
import shutil
from dataclasses import dataclass
from pathlib import Path

from ofpm.ollama.store import (
    OllamaModel,
    blob_path,
    blobs_dir,
    manifests_dir,
    resolve_model,
    sha256_file,
)


@dataclass(frozen=True)
class CopyResult:
    model: OllamaModel
    source_models_dir: Path
    target_models_dir: Path
    copied_files: tuple[Path, ...]
    skipped_files: tuple[Path, ...]
    planned_files: tuple[Path, ...]
    dry_run: bool


@dataclass(frozen=True)
class VerifyResult:
    model: OllamaModel
    checked_files: tuple[Path, ...]
    errors: tuple[str, ...]


def _copy_file(source: Path, destination: Path, *, dry_run: bool) -> str:
    if destination.exists():
        if not destination.is_file():
            raise ValueError(f"destination exists and is not a file: {destination}")
        if source.stat().st_size == destination.stat().st_size and filecmp.cmp(source, destination, shallow=False):
            return "skipped"
        raise ValueError(f"destination file conflict: {destination}")
    if dry_run:
        return "planned"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return "copied"


def copy_model(source_models_dir: Path, target_models_dir: Path, model_ref: str, *, dry_run: bool = False) -> CopyResult:
    source = source_models_dir.expanduser().resolve()
    target = target_models_dir.expanduser().resolve()
    model = resolve_model(source, model_ref)
    if model.missing_blobs:
        missing = ", ".join(f"sha256-{digest}" for digest in model.missing_blobs)
        raise ValueError(f"source model has missing blobs: {missing}")

    copied: list[Path] = []
    skipped: list[Path] = []
    planned: list[Path] = []

    manifest_destination = manifests_dir(target) / model.manifest_relpath
    status = _copy_file(model.manifest_path, manifest_destination, dry_run=dry_run)
    if status == "copied":
        copied.append(manifest_destination)
    elif status == "skipped":
        skipped.append(manifest_destination)
    else:
        planned.append(manifest_destination)

    for digest in model.digests:
        source_blob = blob_path(source, digest)
        destination_blob = blobs_dir(target) / source_blob.name
        status = _copy_file(source_blob, destination_blob, dry_run=dry_run)
        if status == "copied":
            copied.append(destination_blob)
        elif status == "skipped":
            skipped.append(destination_blob)
        else:
            planned.append(destination_blob)

    return CopyResult(
        model=model,
        source_models_dir=source,
        target_models_dir=target,
        copied_files=tuple(copied),
        skipped_files=tuple(skipped),
        planned_files=tuple(planned),
        dry_run=dry_run,
    )


def verify_model(models_dir: Path, model_ref: str, *, check_hash: bool = True) -> VerifyResult:
    root = models_dir.expanduser().resolve()
    model = resolve_model(root, model_ref)
    errors: list[str] = []
    checked: list[Path] = [model.manifest_path]

    for digest in model.digests:
        path = blob_path(root, digest)
        checked.append(path)
        if not path.exists():
            errors.append(f"missing blob: {path}")
            continue
        if not path.is_file():
            errors.append(f"blob is not a file: {path}")
            continue
        if check_hash:
            actual = sha256_file(path)
            if actual != digest:
                errors.append(f"blob digest mismatch: {path} expected sha256-{digest} got sha256-{actual}")

    return VerifyResult(
        model=model,
        checked_files=tuple(checked),
        errors=tuple(errors),
    )
