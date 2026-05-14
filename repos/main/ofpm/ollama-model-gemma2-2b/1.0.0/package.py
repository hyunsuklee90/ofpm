from __future__ import annotations


def package():
    return {
        "schema_version": "1",
        "package_id": "ollama-model-gemma2-2b",
        "version": "1.0.0",
        "target": {
            "os": "linux",
            "distro": "ubuntu",
            "release": "22.04",
            "arch": "amd64",
        },
        "install_root": "payloads/ollama-model-gemma2-2b/1.0.0",
        "depends": [
            {
                "package_id": "ollama-runtime",
                "version": "0.23.2",
                "required": False,
                "reason": "usable later when an Ollama runtime is installed and pointed at the managed model store",
            }
        ],
        "metadata": {
            "description": "offline gemma2:2b ollama manifest/blob backup stored inside repos/main",
            "source_kind": "repo-internal",
            "origin_relroot": "packages/ollama-model-gemma2-2b/1.0.0/payload/models-backup",
            "pi_model": {
                "provider": "ollama",
                "id": "gemma2:2b",
                "name": "Gemma 2 2B Local",
            },
            "verification_notes": [
                "manifest closure must be verified before restore",
                "list-only checks are insufficient",
                "this source backup currently contains multiple model manifests; shared-store merge will de-duplicate identical blobs",
            ],
        },
        "env": {
            "set": {
                "OLLAMA_MODELS": "@managed_root/data/ollama-models"
            }
        },
        "files": [
            {
                "source_dir": "payload/models-backup",
                "target_dir": "models-backup",
                "mode": "0644",
            }
        ],
    }
