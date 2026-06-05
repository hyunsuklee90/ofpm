from __future__ import annotations

from ofpm.recipes import OfpmManagedFilesRecipe


class Recipe(OfpmManagedFilesRecipe):
    def __init__(self):
        super().__init__(
            package_id="cds",
            version="0.1.0",
            target={"os": "linux", "distro": "", "release": "", "arch": "amd64"},
            install_root="payloads/cds/0.1.0",
            depends=[],
            plugins=[],
            plugin_data=[],
            metadata={
                "description": "portable cds shell environment release snapshot with user-local config and data homes",
                "source_kind": "project-export",
                "shell_entrypoint": "bashrc.sh",
                "usage_hint": "source <managed_root>/payloads/cds/current/bashrc.sh",
                "user_home_hint": "~/.local/cds",
            },
            env={},
            files=[
                {
                    "source_dir": "payload",
                    "target_dir": "",
                }
            ],
        )


RECIPE = Recipe()
