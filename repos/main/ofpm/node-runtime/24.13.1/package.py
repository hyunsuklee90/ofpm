from __future__ import annotations


def package():
    return {
        "schema_version": "1",
        "package_id": "node-runtime",
        "version": "24.13.1",
        "target": {
            "os": "linux",
            "distro": "ubuntu",
            "release": "22.04",
            "arch": "amd64",
        },
        "install_root": "payloads/node-runtime/24.13.1",
        "depends": [],
        "metadata": {
            "description": "offline node runtime archive stored inside repos/main",
            "source_kind": "repo-internal",
            "origin_relroot": "packages/node-runtime/24.13.1/payload",
        },
        "env": {
            "prepend_path": {
                "PATH": ["@package_root/bin"]
            }
        },
        "files": [
            {
                "source": "payload/node-v24.13.1-linux-x64.tar.xz",
                "target": "node-v24.13.1-linux-x64.tar.xz",
                "mode": "0644",
            }
        ],
    }
