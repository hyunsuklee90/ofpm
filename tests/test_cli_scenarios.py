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
            public_hello = managed_root / "bin" / "hello"
            self.assertTrue(public_hello.is_symlink())
            self.assertEqual(public_hello.resolve(), managed_root / "payloads" / "hello-tool" / "1.0.0" / "bin" / "hello")

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
            self.assertFalse(public_hello.exists())

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

    def test_package_init_verify_test_and_repo_import_package(self) -> None:
        with self.make_tempdir("ofpm-cli-package-") as temp_dir:
            scenario_root = Path(temp_dir)
            rootfs = scenario_root / "rootfs"
            repo_path = scenario_root / "repo"
            package_root = scenario_root / "builder" / "packaging" / "ofpm"
            env = self.scenario_env(scenario_root)
            managed_root = rootfs / "home" / "tester" / ".ofpm"

            repo_path.mkdir(parents=True, exist_ok=True)
            self.run_cli("repo", "add", "pkgtest", str(repo_path), "--scope", "user", env=env)

            initialized = self.run_cli(
                "package",
                "init",
                str(package_root),
                "--package-id",
                "cds",
                "--version",
                "0.1.0",
                "--description",
                "portable cds fixture",
                env=env,
            )
            self.assertIn("initialized package dir", initialized.stdout)

            payload_bin = package_root / "payload" / "bin"
            payload_bin.mkdir(parents=True, exist_ok=True)
            script_path = payload_bin / "cds"
            script_path.write_text("#!/usr/bin/env bash\necho cds-fixture\n", encoding="utf-8")

            verified = self.run_cli("package", "verify", str(package_root), env=env)
            self.assertIn(" - result: verified", verified.stdout)

            tested = self.run_cli("package", "test", str(package_root), env=env)
            self.assertIn(" - result: passed", tested.stdout)

            imported = self.run_cli(
                "repo",
                "import-package",
                "pkgtest",
                str(package_root),
                env=env,
            )
            self.assertIn("imported package dir into repo: cds", imported.stdout)

            manifest_path = repo_path / "ofpm" / "cds" / "0.1.0" / "package.py"
            payload_path = repo_path / "ofpm" / "cds" / "0.1.0" / "payload" / "bin" / "cds"
            self.assertTrue(manifest_path.exists())
            self.assertTrue(payload_path.exists())

            installed = self.run_cli(
                "install",
                "cds",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("installed package: cds 0.1.0", installed.stdout)

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
                package_id="node",
                version="24.13.1",
                updated_at="2026-05-14T00:00:00+00:00",
                root_kind="user",
            )
            write_installed_state(
                system_root,
                package_id="node",
                version="24.13.1",
                updated_at="2026-05-14T00:00:01+00:00",
                root_kind="system",
            )
            self.assertTrue(managed_state_file(user_root, "node").exists())
            self.assertTrue(managed_state_file(system_root, "node").exists())

    def test_apt_build_repo_and_activate_flow(self) -> None:
        with self.make_tempdir("ofpm-cli-apt-local-") as temp_dir:
            scenario_root = Path(temp_dir)
            repo_path = scenario_root / "repo"
            package_root = repo_path / "apt" / "zstd" / "1.0.0"
            payload_root = package_root / "payload"
            pool_dir = payload_root / "pool"
            pool_dir.mkdir(parents=True, exist_ok=True)
            (pool_dir / "zstd_1.0.0_amd64.deb").write_bytes(b"fake-deb")

            cli.dump_package_file(
                package_root / "package.py",
                {
                    "schema_version": "1",
                    "provider": "apt",
                    "package_name": "zstd",
                    "package_version": "1.0.0",
                    "requested_package": "zstd",
                    "with_deps": True,
                    "context": {"distro": "ubuntu", "release": "22.04", "arch": "amd64"},
                    "downloaded_at": "2026-05-18T00:00:00+00:00",
                    "artifact_root": str(payload_root),
                    "packages": [
                        {
                            "name": "zstd",
                            "version": "1.0.0",
                            "filename": "zstd_1.0.0_amd64.deb",
                            "path": str(pool_dir / "zstd_1.0.0_amd64.deb"),
                            "size": 8,
                        }
                    ],
                    "apt_metadata": {"Package": "zstd", "Version": "1.0.0"},
                },
            )

            source_path = scenario_root / "zstd.list"
            args_build = argparse.Namespace(repo_id="main", package="zstd", version=None)
            args_activate = argparse.Namespace(
                repo_id="main",
                package="zstd",
                version=None,
                source_name=None,
                source_path=str(source_path),
                no_update=False,
            )
            args_deactivate = argparse.Namespace(
                package="zstd",
                source_name=None,
                source_path=str(source_path),
                no_update=True,
            )

            def fake_run(cmd, **kwargs):
                if cmd[:2] == ["dpkg-scanpackages", "pool"]:
                    return subprocess.CompletedProcess(cmd, 0, stdout="Package: zstd\nVersion: 1.0.0\n\n", stderr="")
                if cmd[0] == "apt-get":
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                raise AssertionError(f"unexpected command: {cmd}")

            with mock.patch("ofpm.cli.resolve_registered_repo_path", return_value=repo_path):
                with mock.patch("subprocess.run", side_effect=fake_run):
                    build_out = io.StringIO()
                    with contextlib.redirect_stdout(build_out):
                        result = cli.cmd_apt_build_repo(args_build)
                    self.assertEqual(result, 0)
                    self.assertIn("built apt local repo: zstd", build_out.getvalue())
                    self.assertTrue((payload_root / "Packages").exists())
                    self.assertTrue((payload_root / "Packages.gz").exists())

                    activate_out = io.StringIO()
                    with contextlib.redirect_stdout(activate_out):
                        result = cli.cmd_apt_activate(args_activate)
                    self.assertEqual(result, 0)
                    self.assertIn("activated apt local repo: zstd", activate_out.getvalue())
                    self.assertTrue(source_path.exists())
                    self.assertIn("deb [trusted=yes] file:", source_path.read_text(encoding="utf-8"))

                    deactivate_out = io.StringIO()
                    with contextlib.redirect_stdout(deactivate_out):
                        result = cli.cmd_apt_deactivate(args_deactivate)
                    self.assertEqual(result, 0)
                    self.assertFalse(source_path.exists())

    def test_dnf_repo_file_text(self) -> None:
        repo_text = cli.dnf_repo_file_text("offline-main", Path("/tmp/offline-main"))
        self.assertIn("[offline-main]", repo_text)
        self.assertIn("baseurl=file:///tmp/offline-main", repo_text)
        self.assertIn("enabled=1", repo_text)

    def test_apt_commands_helper_output(self) -> None:
        args = argparse.Namespace(
            repo_id="main",
            package="zstd",
            version=None,
            with_deps=True,
            source_name=None,
        )
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            result = cli.cmd_apt_commands(args)
        self.assertEqual(result, 0)
        output = captured.getvalue()
        self.assertIn("apt helper for: zstd", output)
        self.assertIn("ofpm apt download zstd --with-deps", output)
        self.assertIn("ofpm apt build-repo main zstd", output)
        self.assertIn("sudo ofpm apt activate main zstd --source-name ofpm-zstd", output)
        self.assertIn("dpkg -s zstd >/dev/null 2>&1 || sudo apt install zstd", output)

    def test_install_ofpm_writes_launcher_profile_and_symlink(self) -> None:
        with self.make_tempdir("ofpm-install-self-") as temp_dir:
            temp_root = Path(temp_dir)
            launcher_path = temp_root / "opt" / "ofpm" / "bin" / "ofpm"
            profile_path = temp_root / "etc" / "profile.d" / "ofpm.sh"
            bashrc_path = temp_root / "etc" / "bash.bashrc"
            bashrc_path.parent.mkdir(parents=True, exist_ok=True)
            bashrc_path.write_text("# system bashrc\n", encoding="utf-8")

            args = argparse.Namespace(
                output=str(launcher_path),
                python="/usr/bin/python3",
                source_root=str(REPO_ROOT),
                root="system",
                profile_path=str(profile_path),
                bashrc_path=str(bashrc_path),
                symlink_path=None,
                no_profile=False,
                no_symlink=False,
                force=False,
            )

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                result = cli.cmd_install_cli(args)
            self.assertEqual(result, 0)

            self.assertTrue(launcher_path.exists())
            self.assertTrue(os.access(launcher_path, os.X_OK))
            launcher_text = launcher_path.read_text(encoding="utf-8")
            self.assertIn('exec "/usr/bin/python3" -m ofpm "$@"', launcher_text)
            self.assertIn(f'export PYTHONPATH="{REPO_ROOT}${{PYTHONPATH:+:$PYTHONPATH}}"', launcher_text)

            self.assertTrue(profile_path.exists())
            profile_text = profile_path.read_text(encoding="utf-8")
            self.assertIn(f'export OFPM_ROOT="{launcher_path.parent.parent}"', profile_text)
            self.assertIn(f'export PATH="{launcher_path.parent}:$PATH"', profile_text)
            bashrc_text = bashrc_path.read_text(encoding="utf-8")
            self.assertEqual(bashrc_text.count("# >>> ofpm >>>"), 1)
            self.assertIn(f'[ -r "{profile_path}" ] && source "{profile_path}"', bashrc_text)

            output = captured.getvalue()
            self.assertIn("installed ofpm launcher", output)
            self.assertIn(f" - output: {launcher_path}", output)
            self.assertIn(f" - shell hook: {profile_path}", output)
            self.assertIn(f" - bashrc hook: {bashrc_path}", output)
            self.assertIn(" - command link: disabled", output)

    def test_install_ofpm_user_updates_single_bashrc_block(self) -> None:
        with self.make_tempdir("ofpm-install-user-") as temp_dir:
            temp_root = Path(temp_dir)
            home = temp_root / "home" / "tester"
            bashrc_path = home / ".bashrc"
            bashrc_path.parent.mkdir(parents=True, exist_ok=True)
            bashrc_path.write_text("# existing line\n", encoding="utf-8")
            launcher_path = home / ".ofpm" / "bin" / "ofpm"

            args = argparse.Namespace(
                output=str(launcher_path),
                python="/usr/bin/python3",
                source_root=str(REPO_ROOT),
                root="user",
                profile_path=str(bashrc_path),
                bashrc_path=None,
                symlink_path=None,
                no_profile=False,
                no_symlink=False,
                force=False,
            )

            first = io.StringIO()
            with contextlib.redirect_stdout(first):
                result = cli.cmd_install_cli(args)
            self.assertEqual(result, 0)

            first_bashrc = bashrc_path.read_text(encoding="utf-8")
            self.assertEqual(first_bashrc.count("# >>> ofpm >>>"), 1)
            self.assertEqual(first_bashrc.count("# <<< ofpm <<<"), 1)
            self.assertIn('export OFPM_ROOT="', first_bashrc)
            self.assertIn(f'export PATH="{launcher_path.parent}:$PATH"', first_bashrc)

            second = io.StringIO()
            with contextlib.redirect_stdout(second):
                result = cli.cmd_install_cli(args)
            self.assertEqual(result, 0)

            second_bashrc = bashrc_path.read_text(encoding="utf-8")
            self.assertEqual(second_bashrc.count("# >>> ofpm >>>"), 1)
            self.assertEqual(second_bashrc.count("# <<< ofpm <<<"), 1)


if __name__ == "__main__":
    unittest.main()
