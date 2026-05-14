from __future__ import annotations


def package():
    return {
        "schema_version": "1",
        "package_id": "helper-lib",
        "version": "1.0.0",
        "target": {
            "os": "linux",
            "distro": "ubuntu",
            "release": "22.04",
            "arch": "amd64",
        },
        "install_root": "payloads/helper-lib/1.0.0",
        "depends": [],
        "metadata": {
            "description": "tiny dependency payload for minimal test repo",
        },
        "files": [
            {
                "source_dir": "payload",
                "target_dir": "",
                "mode": "0644",
            }
        ],
    }
