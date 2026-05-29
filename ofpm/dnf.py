from __future__ import annotations

import configparser
import io
import re
from pathlib import Path

from ofpm.process_ui import run_command_live


def safe_path_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "item"


def dnf_repo_file_text(repo_id: str, repo_root: Path) -> str:
    parser = configparser.ConfigParser()
    parser[repo_id] = {
        "name": f"ofpm offline repo ({repo_id})",
        "baseurl": f"file://{repo_root.resolve().as_posix()}",
        "enabled": "1",
        "gpgcheck": "0",
        "repo_gpgcheck": "0",
        "metadata_expire": "never",
    }
    buffer = io.StringIO()
    parser.write(buffer, space_around_delimiters=False)
    return buffer.getvalue()


def is_dnf_local_repo_root(path: Path) -> bool:
    return (path / "repodata" / "repomd.xml").exists()


def find_dnf_local_repo_roots(root: Path) -> list[Path]:
    resolved_root = root.expanduser().resolve()
    if is_dnf_local_repo_root(resolved_root):
        return [resolved_root]

    results: list[Path] = []
    seen: set[Path] = set()
    for repomd_path in resolved_root.rglob("repomd.xml"):
        repo_root = repomd_path.parent.parent
        if repo_root in seen:
            continue
        if is_dnf_local_repo_root(repo_root):
            seen.add(repo_root)
            results.append(repo_root)
    return sorted(results)


def build_dnf_local_repo(repo_root: Path) -> Path:
    if not repo_root.exists():
        raise ValueError(f"dnf repo root not found: {repo_root}")
    rpm_files = sorted(repo_root.glob("*.rpm"))
    if not rpm_files:
        raise ValueError(f"no rpm files found under {repo_root}")
    try:
        run_command_live(
            ["createrepo_c", str(repo_root)],
            label=f"createrepo {repo_root.name}",
        )
    except FileNotFoundError as exc:
        raise ValueError("missing required builder tool: createrepo_c") from exc
    return repo_root
