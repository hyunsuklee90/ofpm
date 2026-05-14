from __future__ import annotations


def package():
    return {
        "schema_version": "1",
        "package_id": "pi-agent",
        "version": "0.74.0",
        "target": {
            "os": "linux",
            "distro": "ubuntu",
            "release": "22.04",
            "arch": "amd64",
        },
        "install_root": "payloads/pi-agent/0.74.0",
        "depends": [
            {
                "package_id": "node-runtime",
                "version": "24.13.1",
                "required": True,
                "reason": "pi-agent is distributed as a Node-based CLI",
            },
            {
                "package_id": "ollama-runtime",
                "version": "0.23.2",
                "required": False,
                "reason": "needed when pi-agent should talk to a local Ollama runtime",
            },
            {
                "package_id": "ollama-model-gemma4-e4b",
                "version": "1.0.0",
                "required": False,
                "reason": "needed when the local Ollama runtime should serve gemma4:e4b",
            },
            {
                "package_id": "ollama-model-gemma2-2b",
                "version": "1.0.0",
                "required": False,
                "reason": "needed when the local Ollama runtime should serve gemma2:2b",
            },
        ],
        "metadata": {
            "description": "offline pi tgz, npm cache, and helper binaries stored inside repos/main",
            "source_kind": "repo-internal",
            "origin_relroot": "packages/pi-agent/0.74.0/payload",
        },
        "env": {
            "set": {
                "PI_CODING_AGENT_DIR": "@config_dir"
            },
            "prepend_path": {
                "PATH": ["@package_root/bin"]
            },
        },
        "files": [
            {
                "source": "payload/archives/earendil-works-pi-coding-agent-0.74.0.tgz",
                "target": "archives/earendil-works-pi-coding-agent-0.74.0.tgz",
                "mode": "0644",
            },
            {
                "source": "payload/bin/rg",
                "target": "bin/rg",
                "mode": "0755",
            },
            {
                "source": "payload/bin/fd",
                "target": "bin/fd",
                "mode": "0755",
            },
            {
                "source_dir": "payload/npm-cache",
                "target_dir": "npm-cache",
                "file_count_hint": 1004,
                "mode": "0644",
            },
        ],
    }
