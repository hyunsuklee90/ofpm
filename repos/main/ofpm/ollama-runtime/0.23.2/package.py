from __future__ import annotations


def package():
    return {
        "schema_version": "1",
        "package_id": "ollama-runtime",
        "version": "0.23.2",
        "target": {
            "os": "linux",
            "distro": "ubuntu",
            "release": "22.04",
            "arch": "amd64",
        },
        "install_root": "payloads/ollama-runtime/0.23.2",
        "depends": [],
        "metadata": {
            "description": "offline ollama runtime artifacts stored inside repos/main",
            "source_kind": "repo-internal",
            "origin_relroot": "packages/ollama-runtime/0.23.2/payload",
        },
        "env": {
            "set": {
                "OLLAMA_LIBRARY_PATH": "@library_dir"
            },
            "prepend_path": {
                "PATH": ["@package_root/bin"],
                "LD_LIBRARY_PATH": ["@library_dir"]
            },
        },
        "files": [
            {
                "source": "payload/archives/ollama-linux-amd64.tar.zst",
                "target": "archives/ollama-linux-amd64.tar.zst",
                "mode": "0644",
            }
        ],
    }
