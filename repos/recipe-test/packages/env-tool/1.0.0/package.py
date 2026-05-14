from __future__ import annotations


def package():
    return {
        "schema_version": "1",
        "package_id": "env-tool",
        "version": "1.0.0",
        "target": {
            "os": "linux",
            "distro": "ubuntu",
            "release": "22.04",
            "arch": "amd64",
        },
        "install_root": "payloads/env-tool/1.0.0",
        "depends": [],
        "env": {
            "set": {
                "ENV_TOOL_HOME": "@package_root",
            },
            "prepend_path": {
                "PATH": ["@package_root/bin"],
                "LD_LIBRARY_PATH": ["@package_root/lib/env-tool"],
            },
        },
        "metadata": {
            "description": "tiny env-focused package for recipe-test repo",
            "source_kind": "repo-internal",
            "layout_experiment": "package.py + payload",
        },
        "files": [
            {
                "source_dir": "payload",
                "target_dir": "",
                "mode": "0755",
            }
        ],
    }
