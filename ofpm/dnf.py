from __future__ import annotations

import configparser
import io
import subprocess
from pathlib import Path


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


def build_dnf_local_repo(repo_root: Path) -> Path:
    if not repo_root.exists():
        raise ValueError(f"dnf repo root not found: {repo_root}")
    rpm_files = sorted(repo_root.glob("*.rpm"))
    if not rpm_files:
        raise ValueError(f"no rpm files found under {repo_root}")
    try:
        subprocess.run(
            ["createrepo_c", str(repo_root)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ValueError("missing required builder tool: createrepo_c") from exc
    return repo_root
