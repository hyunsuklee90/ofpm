from __future__ import annotations

import argparse
import json
from pathlib import Path

from ofpm.ollama.copy import copy_model, verify_model
from ofpm.ollama.store import default_models_dir, list_models


def _models_dir(raw: str | None) -> Path:
    return Path(raw).expanduser().resolve() if raw else default_models_dir()


def _format_bytes(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def _model_json(model: object) -> dict[str, object]:
    return {
        "ref": model.ref,
        "full_ref": model.full_ref,
        "manifest": str(model.manifest_path),
        "manifest_relpath": model.manifest_relpath.as_posix(),
        "blob_count": len(model.digests),
        "blob_bytes": model.total_blob_size,
        "missing_blobs": [f"sha256-{digest}" for digest in model.missing_blobs],
    }


def cmd_list(args: argparse.Namespace) -> int:
    models_dir = _models_dir(args.models_dir)
    models = list_models(models_dir)
    if args.json:
        print(json.dumps({"models_dir": str(models_dir), "models": [_model_json(model) for model in models]}, indent=2))
        return 0
    if not models:
        print(f"no ollama models found in: {models_dir}")
        print("expected layout: manifests/ and blobs/ under the models directory")
        return 0
    print("ollama models:")
    print(f"models dir: {models_dir}")
    print(f"model count: {len(models)}")
    for model in models:
        status = "ok" if not model.missing_blobs else f"missing blobs={len(model.missing_blobs)}"
        print(
            " - "
            f"{model.ref} "
            f"[blobs={len(model.digests)}] "
            f"[size={_format_bytes(model.total_blob_size)}] "
            f"[{status}]"
        )
        if args.verbose:
            print(f"   full ref: {model.full_ref}")
            print(f"   manifest: {model.manifest_path}")
    return 0


def cmd_copy(args: argparse.Namespace) -> int:
    source = _models_dir(args.source)
    target = Path(args.target).expanduser().resolve()
    try:
        result = copy_model(source, target, args.model, dry_run=args.dry_run)
    except ValueError as exc:
        print(str(exc))
        return 1
    if args.json:
        print(
            json.dumps(
                {
                    "model": _model_json(result.model),
                    "source_models_dir": str(result.source_models_dir),
                    "target_models_dir": str(result.target_models_dir),
                    "dry_run": result.dry_run,
                    "copied_files": [str(path) for path in result.copied_files],
                    "skipped_files": [str(path) for path in result.skipped_files],
                    "planned_files": [str(path) for path in result.planned_files],
                },
                indent=2,
            )
        )
        return 0
    action = "planned ollama model copy" if result.dry_run else "copied ollama model"
    print(f"{action}: {result.model.ref}")
    print(f" - source models dir: {result.source_models_dir}")
    print(f" - target models dir: {result.target_models_dir}")
    print(f" - manifest: {result.model.manifest_relpath.as_posix()}")
    print(f" - referenced blobs: {len(result.model.digests)}")
    print(f" - copied files: {len(result.copied_files)}")
    print(f" - skipped files: {len(result.skipped_files)}")
    if result.dry_run:
        print(f" - planned files: {len(result.planned_files)}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    models_dir = _models_dir(args.models_dir)
    try:
        result = verify_model(models_dir, args.model, check_hash=not args.no_hash)
    except ValueError as exc:
        print(str(exc))
        return 1
    if args.json:
        print(
            json.dumps(
                {
                    "model": _model_json(result.model),
                    "models_dir": str(models_dir),
                    "checked_files": [str(path) for path in result.checked_files],
                    "errors": list(result.errors),
                    "result": "verified" if not result.errors else "failed",
                },
                indent=2,
            )
        )
        return 0 if not result.errors else 1
    print(f"verified ollama model: {result.model.ref}")
    print(f" - models dir: {models_dir}")
    print(f" - manifest: {result.model.manifest_relpath.as_posix()}")
    print(f" - checked files: {len(result.checked_files)}")
    print(f" - hash check: {'skipped' if args.no_hash else 'enabled'}")
    if result.errors:
        print(" - result: failed")
        for error in result.errors:
            print(f"   - {error}")
        return 1
    print(" - result: verified")
    return 0
