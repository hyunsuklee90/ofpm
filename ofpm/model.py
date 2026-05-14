from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackageFile:
    source: Path
    target: str
    mode: str | None = None


@dataclass(frozen=True)
class StagedBlob:
    sha256: str
    size: int
    store_path: Path
