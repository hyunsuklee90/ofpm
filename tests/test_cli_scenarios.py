from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ofpm import cli
from ofpm.state_db import managed_state_file


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = REPO_ROOT / "tests" / "fixtures" / "repos" / "minimal"
WORK_ROOT = REPO_ROOT / "tests" / "work"


def write_installed_state(
    managed_root: Path,
    *,
    package_id: str,
    version: str,
    updated_at: str,
    root_kind: str,
) -> None:
    state = {
        "schema_version": "1",
        "updated_at": updated_at,
        "root_kind": root_kind,
        "managed_root": str(managed_root),
        "package": {
            "package_id": package_id,
            "package_version": version,
            "profile_id": "ubuntu-22.04",
            "install_root": f"payloads/{package_id}/{version}",
        },
    }
    path = managed_state_file(managed_root, package_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


class CliScenarioTests(unittest.TestCase):
    def make_tempdir(self, prefix: str) -> tempfile.TemporaryDirectory[str]:
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(prefix=prefix, dir=WORK_ROOT)

    def scenario_env(self, scenario_root: Path) -> dict[str, str]:
        home = scenario_root / "rootfs" / "home" / "tester"
        config = home / ".config"
        home.mkdir(parents=True, exist_ok=True)
        config.mkdir(parents=True, exist_ok=True)
        return {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
        }

    def run_cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        base_env = os.environ.copy()
        base_env["PYTHONDONTWRITEBYTECODE"] = "1"
        if env:
            base_env.update(env)
        return subprocess.run(
            [sys.executable, "-m", "ofpm", *args],
            cwd=REPO_ROOT,
            env=base_env,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_minimal_repo_roundtrip_and_env_output(self) -> None:
        with self.make_tempdir("ofpm-cli-minimal-") as temp_dir:
            scenario_root = Path(temp_dir)
            rootfs = scenario_root / "rootfs"
            shutil.copytree(FIXTURE_REPO, scenario_root / "repo")
            env = self.scenario_env(scenario_root)
            managed_root = rootfs / "home" / "tester" / ".ofpm"

            added = self.run_cli(
                "repo",
                "add",
                "test",
                str(scenario_root / "repo"),
                "--scope",
                "user",
                env=env,
            )
            self.assertIn("registered repo", added.stdout)

            install = self.run_cli(
                "install",
                "hello-tool",
                "--root",
                "user",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("installed package: hello-tool 1.0.0", install.stdout)

            listed = self.run_cli(
                "list",
                "--installed",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("hello-tool 1.0.0", listed.stdout)

            state = self.run_cli(
                "state",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn(f"managed root: {managed_root}", state.stdout)
            self.assertIn("installed package count: 1", state.stdout)

            verify = self.run_cli(
                "verify",
                "hello-tool",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn(" - result: verified", verify.stdout)

            env_output = self.run_cli(
                "install",
                "env-tool",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("installed package: env-tool 1.0.0", env_output.stdout)
            env_bash = self.run_cli(
                "env",
                "package",
                "env-tool",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("ENV_TOOL_HOME", env_bash.stdout)
            self.assertIn("LD_LIBRARY_PATH", env_bash.stdout)

            removed = self.run_cli(
                "remove",
                "hello-tool",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("removed package: hello-tool 1.0.0", removed.stdout)

            listed_again = self.run_cli(
                "list",
                "--installed",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertNotIn("hello-tool 1.0.0", listed_again.stdout)

    def test_source_add_and_repo_import_emit_package_py_layout(self) -> None:
        with self.make_tempdir("ofpm-cli-import-") as temp_dir:
            scenario_root = Path(temp_dir)
            rootfs = scenario_root / "rootfs"
            repo_path = scenario_root / "repo"
            source_path = scenario_root / "source-hello"
            env = self.scenario_env(scenario_root)
            managed_root = rootfs / "home" / "tester" / ".ofpm"

            (source_path / "bin").mkdir(parents=True, exist_ok=True)
            (source_path / "bin" / "hello-import").write_text(
                "#!/usr/bin/env bash\necho hello-import\n",
                encoding="utf-8",
            )

            repo_path.mkdir(parents=True, exist_ok=True)
            self.run_cli("repo", "add", "importtest", str(repo_path), "--scope", "user", env=env)
            self.run_cli("source", "add", "hello-import", str(source_path), env=env)

            imported = self.run_cli(
                "repo",
                "import",
                "importtest",
                "--source",
                "hello-import",
                "--package",
                "hello-import",
                "--version",
                "1.0.0",
                env=env,
            )
            self.assertIn("imported source into repo: hello-import", imported.stdout)

            manifest_path = repo_path / "ofpm" / "hello-import" / "1.0.0" / "package.py"
            payload_path = repo_path / "ofpm" / "hello-import" / "1.0.0" / "payload" / "bin" / "hello-import"
            self.assertTrue(manifest_path.exists())
            self.assertTrue(payload_path.exists())

            package_data = cli.load_package_file(manifest_path)
            self.assertIn("target", package_data)
            self.assertEqual(package_data["target"]["distro"], "ubuntu")
            self.assertEqual(package_data["profile_id"], "ubuntu-22.04")

            listed = self.run_cli("list", "--all", env=env)
            self.assertIn("hello-import 1.0.0", listed.stdout)

            installed = self.run_cli(
                "install",
                "hello-import",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("installed package: hello-import 1.0.0", installed.stdout)

    def test_dependency_and_ambiguous_root_policy(self) -> None:
        with self.make_tempdir("ofpm-cli-policy-") as temp_dir:
            scenario_root = Path(temp_dir)
            rootfs = scenario_root / "rootfs"
            shutil.copytree(FIXTURE_REPO, scenario_root / "repo")
            env = self.scenario_env(scenario_root)
            user_root = rootfs / "home" / "tester" / ".ofpm"
            system_root = rootfs / "opt" / "ofpm"

            self.run_cli(
                "repo",
                "add",
                "test",
                str(scenario_root / "repo"),
                "--scope",
                "user",
                env=env,
            )

            missing_dep = subprocess.run(
                [sys.executable, "-m", "ofpm", "install", "app-with-dep", "--root-path", str(user_root)],
                cwd=REPO_ROOT,
                env={**os.environ, **env, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(missing_dep.returncode, 0)
            self.assertIn("missing required dependency: helper-lib 1.0.0", missing_dep.stderr + missing_dep.stdout)

            self.run_cli("install", "helper-lib", "--root-path", str(user_root), env=env)
            installed = self.run_cli("install", "app-with-dep", "--root-path", str(user_root), env=env)
            self.assertIn("installed package: app-with-dep 1.0.0", installed.stdout)

            self.run_cli("install", "hello-tool", "--root-path", str(user_root), env=env)
            self.run_cli("install", "hello-tool", "--root", "system", "--root-path", str(system_root), env=env)

            args = argparse.Namespace(root="user", root_path=None, all_roots=True)
            with mock.patch(
                "ofpm.cli.managed_root",
                side_effect=lambda kind: user_root if kind == "user" else system_root,
            ):
                installed = cli.installed_states_for_query(args)
            hello_roots = [item["selected_root_kind"] for item in installed if item["package_id"] == "hello-tool"]
            self.assertEqual(sorted(hello_roots), ["system", "user"])

            captured = io.StringIO()
            with mock.patch(
                "ofpm.cli.managed_root",
                side_effect=lambda kind: user_root if kind == "user" else system_root,
            ):
                with contextlib.redirect_stdout(captured):
                    resolved = cli.resolve_installed_state_for_action(args, "hello-tool")

            self.assertIsNone(resolved)
            output = captured.getvalue()
            self.assertIn("package is installed in multiple roots: hello-tool", output)
            self.assertIn("root=user", output)
            self.assertIn("root=system", output)

    def test_write_installed_state_helper(self) -> None:
        with self.make_tempdir("ofpm-cli-helper-") as temp_dir:
            temp_root = Path(temp_dir)
            user_root = temp_root / "user-root"
            system_root = temp_root / "system-root"
            write_installed_state(
                user_root,
                package_id="node-runtime",
                version="24.13.1",
                updated_at="2026-05-14T00:00:00+00:00",
                root_kind="user",
            )
            write_installed_state(
                system_root,
                package_id="node-runtime",
                version="24.13.1",
                updated_at="2026-05-14T00:00:01+00:00",
                root_kind="system",
            )
            self.assertTrue(managed_state_file(user_root, "node-runtime").exists())
            self.assertTrue(managed_state_file(system_root, "node-runtime").exists())


if __name__ == "__main__":
    unittest.main()
