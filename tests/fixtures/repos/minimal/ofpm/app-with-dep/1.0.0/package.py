from __future__ import annotations


def package():
    return {
        "schema_version": "1",
        "package_id": "app-with-dep",
        "version": "1.0.0",
        "target": {
            "os": "linux",
            "distro": "ubuntu",
            "release": "22.04",
            "arch": "amd64",
        },
        "install_root": "payloads/app-with-dep/1.0.0",
        "depends": [
            {
                "package_id": "helper-lib",
                "version": "1.0.0",
            }
        ],
        "metadata": {
            "description": "tiny app with dependency on helper-lib",
        },
        "files": [
            {
                "source_dir": "payload",
                "target_dir": "",
                "mode": "0755",
            }
        ],
    }
