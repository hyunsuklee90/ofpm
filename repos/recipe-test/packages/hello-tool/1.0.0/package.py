from __future__ import annotations


def package():
    return {
        "schema_version": "1",
        "package_id": "hello-tool",
        "version": "1.0.0",
        "target": {
            "os": "linux",
            "distro": "ubuntu",
            "release": "22.04",
            "arch": "amd64",
        },
        "install_root": "payloads/hello-tool/1.0.0",
        "depends": [],
        "env": {
            "prepend_path": {
                "PATH": ["@package_root/bin"],
            }
        },
        "metadata": {
            "description": "tiny executable for recipe-test repo",
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
