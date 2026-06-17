from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest import mock

from ofpm import cli
from ofpm.prepare import get_preparer
from ofpm.repo_data import native_repo_package_root
from ofpm.state_db import managed_state_file


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = REPO_ROOT / "tests" / "fixtures" / "repos" / "minimal"
WORK_ROOT = Path(os.environ.get("OFPM_TEST_WORK_ROOT", "/tmp/ofpm-tests")).resolve()


def keep_test_work() -> bool:
    return os.environ.get("OFPM_TEST_KEEP_WORK", "").strip().lower() in {"1", "true", "yes", "on"}


def cleanup_test_work() -> None:
    if WORK_ROOT.exists():
        shutil.rmtree(WORK_ROOT, ignore_errors=True)


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
    @classmethod
    def setUpClass(cls) -> None:
        if not keep_test_work():
            cleanup_test_work()

    @classmethod
    def tearDownClass(cls) -> None:
        if keep_test_work():
            return
        cleanup_test_work()

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

    def test_help_output_describes_common_flow_and_commands(self) -> None:
        top_level = self.run_cli("-h")
        self.assertIn("Personal offline package manager", top_level.stdout)
        self.assertIn("common target-side flow:", top_level.stdout)
        self.assertIn("ofpm repo add main /path/to/copied/repo", top_level.stdout)
        self.assertIn("install       install a package from an offline repo", top_level.stdout)
        self.assertIn("repo          register and inspect offline repo snapshots", top_level.stdout)

        install_help = self.run_cli("install", "-h")
        self.assertIn("package id to install", install_help.stdout)
        self.assertIn("install a specific version", install_help.stdout)
        self.assertIn("query a repo snapshot directly without registering it", install_help.stdout)

    def make_fake_ofpm_source(self, source_root: Path) -> None:
        package_root = source_root / "ofpm"
        package_root.mkdir(parents=True, exist_ok=True)
        (package_root / "__main__.py").write_text("print('fake ofpm')\n", encoding="utf-8")
        (package_root / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        (source_root / "README.md").write_text("fake source tree\n", encoding="utf-8")
        (source_root / "repos" / "ofpm" / "main" / "demo" / "1.0.0").mkdir(parents=True, exist_ok=True)
        (source_root / "repos" / "ofpm" / "main" / "demo" / "1.0.0" / "package.py").write_text(
            "RECIPE = {'package_id': 'demo'}\n",
            encoding="utf-8",
        )
        (source_root / "repos" / "apt" / "main" / "zstd" / "1.0.0").mkdir(parents=True, exist_ok=True)
        (source_root / "repos" / "apt" / "main" / "zstd" / "1.0.0" / "package.py").write_text(
            "RECIPE = {'package_id': 'zstd'}\n",
            encoding="utf-8",
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
            self.assertFalse((managed_root / "payloads" / "hello-tool").exists())

            listed_again = self.run_cli(
                "list",
                "--installed",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertNotIn("hello-tool 1.0.0", listed_again.stdout)

    def test_repo_import_emit_package_py_layout(self) -> None:
        with self.make_tempdir("ofpm-cli-import-") as temp_dir:
            scenario_root = Path(temp_dir)
            rootfs = scenario_root / "rootfs"
            repo_path = scenario_root / "repo"
            source_path = scenario_root / "source-hello"
            env = self.scenario_env(scenario_root)
            managed_root = rootfs / "home" / "tester" / ".ofpm"

            (source_path / "bin").mkdir(parents=True, exist_ok=True)
            imported_script = source_path / "bin" / "hello-import"
            imported_script.write_text(
                "#!/usr/bin/env bash\necho hello-import\n",
                encoding="utf-8",
            )
            imported_script.chmod(0o755)

            repo_path.mkdir(parents=True, exist_ok=True)
            self.run_cli("repo", "add", "importtest", str(repo_path), env=env)

            imported = self.run_cli(
                "repo",
                "import",
                "importtest",
                "--path",
                str(source_path),
                "--package",
                "hello-import",
                "--version",
                "1.0.0",
                env=env,
            )
            self.assertIn("imported source into repo: source-hello", imported.stdout)

            manifest_path = repo_path / "ofpm" / "hello-import" / "1.0.0" / "package.py"
            payload_path = repo_path / "ofpm" / "hello-import" / "1.0.0" / "payload" / "bin" / "hello-import"
            self.assertTrue(manifest_path.exists())
            self.assertTrue(payload_path.exists())

            package_data = cli.load_package_file(manifest_path)
            self.assertIn("target", package_data)
            self.assertEqual(package_data["target"]["distro"], "ubuntu")
            self.assertEqual(package_data["profile_id"], "ubuntu-22.04")
            self.assertEqual(package_data["files"][0]["source_dir"], "payload")

            verified = self.run_cli("package", "verify", str(repo_path / "ofpm" / "hello-import" / "1.0.0"), env=env)
            self.assertIn(" - result: verified", verified.stdout)

            tested = self.run_cli("package", "test", str(repo_path / "ofpm" / "hello-import" / "1.0.0"), env=env)
            self.assertIn(" - result: passed", tested.stdout)

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

    def test_repo_import_archive_emits_archive_extract_package(self) -> None:
        with self.make_tempdir("ofpm-cli-import-archive-") as temp_dir:
            scenario_root = Path(temp_dir)
            rootfs = scenario_root / "rootfs"
            repo_path = scenario_root / "repo"
            source_path = scenario_root / "source-cds"
            archive_path = scenario_root / "release" / "0.1.0" / "cds-0.1.0.tar.gz"
            meta_path = scenario_root / "release" / "0.1.0" / "ofpm.json"
            env = self.scenario_env(scenario_root)
            managed_root = rootfs / "home" / "tester" / ".ofpm"

            (source_path / "bashrc.d").mkdir(parents=True, exist_ok=True)
            (source_path / "functions" / "cds").mkdir(parents=True, exist_ok=True)
            (source_path / "themes" / "default").mkdir(parents=True, exist_ok=True)
            (source_path / "bashrc.sh").write_text("echo cds\n", encoding="utf-8")
            (source_path / "bashrc.d" / "prompt.sh").write_text("echo prompt\n", encoding="utf-8")
            (source_path / "functions" / "cds" / "cds.sh").write_text("echo cds-fn\n", encoding="utf-8")
            (source_path / "themes" / "default" / "vimrc").write_text("set nocompatible\n", encoding="utf-8")

            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(source_path, arcname="cds-0.1.0")

            meta_path.write_text(
                json.dumps(
                    {
                        "package": "cds",
                        "version": "0.1.0",
                        "profile": "ubuntu-22.04",
                        "description": "portable cds shell environment core release",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            repo_path.mkdir(parents=True, exist_ok=True)
            self.run_cli("repo", "add", "importtest", str(repo_path), env=env)

            try:
                imported = self.run_cli(
                    "repo",
                    "import-archive",
                    "importtest",
                    "--archive",
                    str(archive_path),
                    "--meta",
                    str(meta_path),
                    env=env,
                )
            except subprocess.CalledProcessError as exc:
                self.fail(f"import-archive failed\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}")
            self.assertIn("imported archive into repo: cds-0.1.0.tar.gz", imported.stdout)

            manifest_root = repo_path / "ofpm" / "cds" / "0.1.0"
            manifest_path = manifest_root / "package.py"
            payload_archive = manifest_root / "payload" / "cds-0.1.0.tar.gz"
            self.assertTrue(manifest_path.exists())
            self.assertTrue(payload_archive.exists())

            package_data = cli.load_package_file(manifest_path)
            self.assertEqual(package_data["package_id"], "cds")
            self.assertEqual(package_data["version"], "0.1.0")
            self.assertEqual(package_data["metadata"]["install_mode"], "archive")
            self.assertEqual(package_data["profile_id"], "ubuntu-22.04")

            verified = self.run_cli("package", "verify", str(manifest_root), env=env)
            self.assertIn(" - result: verified", verified.stdout)

            tested = self.run_cli("package", "test", str(manifest_root), env=env)
            self.assertIn(" - result: passed", tested.stdout)

            installed = self.run_cli(
                "install",
                "cds",
                "--repo",
                "importtest",
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("installed package: cds 0.1.0", installed.stdout)
            self.assertIn(f"archive source: {payload_archive}", installed.stdout)
            self.assertIn("stored archive:", installed.stdout)
            self.assertIn("archive size:", installed.stdout)
            self.assertTrue((managed_root / "payloads" / "cds" / "current" / "bashrc.sh").exists())

    def test_package_test_extracts_tar_zst_archive(self) -> None:
        if shutil.which("tar") is None or shutil.which("zstd") is None:
            self.skipTest("tar --zstd support is required")
        with self.make_tempdir("ofpm-cli-tar-zst-") as temp_dir:
            scenario_root = Path(temp_dir)
            source_path = scenario_root / "src" / "demo-1.0.0"
            package_root = scenario_root / "package"
            payload_root = package_root / "payload"
            archive_path = payload_root / "demo-1.0.0.tar.zst"

            (source_path / "bin").mkdir(parents=True, exist_ok=True)
            executable = source_path / "bin" / "demo"
            executable.write_text("#!/usr/bin/env sh\nprintf demo\\n\n", encoding="utf-8")
            executable.chmod(0o755)
            payload_root.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["tar", "--zstd", "-cf", str(archive_path), "-C", str(source_path.parent), source_path.name],
                check=True,
            )

            cli.dump_package_file(
                package_root / "package.py",
                {
                    "schema_version": "1",
                    "package_id": "demo-zst",
                    "version": "1.0.0",
                    "target": {"os": "linux", "distro": "", "release": "", "arch": "amd64"},
                    "install_root": "payloads/demo-zst/1.0.0",
                    "depends": [],
                    "plugins": [],
                    "plugin_data": [],
                    "metadata": {"install_mode": "archive"},
                    "env": {},
                    "files": [{"source": "payload/demo-1.0.0.tar.zst", "target": "demo-1.0.0.tar.zst"}],
                },
            )

            tested = self.run_cli("package", "test", str(package_root))
            self.assertIn(" - result: passed", tested.stdout)

    def test_package_init_verify_test_and_repo_import_package(self) -> None:
        with self.make_tempdir("ofpm-cli-package-") as temp_dir:
            scenario_root = Path(temp_dir)
            rootfs = scenario_root / "rootfs"
            repo_path = scenario_root / "repo"
            package_root = scenario_root / "builder" / "packaging" / "ofpm"
            env = self.scenario_env(scenario_root)
            managed_root = rootfs / "home" / "tester" / ".ofpm"

            repo_path.mkdir(parents=True, exist_ok=True)
            self.run_cli("repo", "add", "pkgtest", str(repo_path), env=env)

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
            script_path.chmod(0o755)

            verified = self.run_cli("package", "verify", str(package_root), env=env)
            self.assertIn(" - result: verified", verified.stdout)

            try:
                tested = self.run_cli("package", "test", str(package_root), env=env)
            except subprocess.CalledProcessError as exc:
                self.fail(f"package test failed\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}")
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
                "--repo",
                "pkgtest",
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

    def write_ollama_blob(self, models_dir: Path, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        blob_path = models_dir / "blobs" / f"sha256-{digest}"
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(content)
        return digest

    def write_ollama_manifest(
        self,
        models_dir: Path,
        name: str,
        tag: str,
        *,
        config_digest: str,
        layer_digests: list[str],
    ) -> Path:
        manifest_path = models_dir / "manifests" / "registry.ollama.ai" / "library" / name / tag
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                    "config": {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": f"sha256:{config_digest}",
                        "size": 1,
                    },
                    "layers": [
                        {
                            "mediaType": "application/vnd.ollama.image.model",
                            "digest": f"sha256:{digest}",
                            "size": 1,
                        }
                        for digest in layer_digests
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return manifest_path

    def test_ollama_list_copy_and_verify_model_store(self) -> None:
        with self.make_tempdir("ofpm-cli-ollama-") as temp_dir:
            scenario_root = Path(temp_dir)
            source = scenario_root / "source-models"
            target = scenario_root / "target-models"
            env = self.scenario_env(scenario_root)

            shared = self.write_ollama_blob(source, b"shared config")
            demo_layer = self.write_ollama_blob(source, b"demo layer")
            other_layer = self.write_ollama_blob(source, b"other layer")
            self.write_ollama_manifest(
                source,
                "demo",
                "latest",
                config_digest=shared,
                layer_digests=[demo_layer],
            )
            self.write_ollama_manifest(
                source,
                "other",
                "latest",
                config_digest=shared,
                layer_digests=[other_layer],
            )

            listed = self.run_cli("ollama", "list", "--models-dir", str(source), env=env)
            self.assertIn("ollama models:", listed.stdout)
            self.assertIn("demo:latest", listed.stdout)
            self.assertIn("other:latest", listed.stdout)

            dry_run = self.run_cli(
                "ollama",
                "copy",
                "demo",
                "--from",
                str(source),
                "--to",
                str(target),
                "--dry-run",
                env=env,
            )
            self.assertIn("planned ollama model copy: demo:latest", dry_run.stdout)
            self.assertFalse(target.exists())

            copied = self.run_cli(
                "ollama",
                "copy",
                "demo",
                "--from",
                str(source),
                "--to",
                str(target),
                env=env,
            )
            self.assertIn("copied ollama model: demo:latest", copied.stdout)
            self.assertTrue((target / "manifests" / "registry.ollama.ai" / "library" / "demo" / "latest").exists())
            self.assertTrue((target / "blobs" / f"sha256-{shared}").exists())
            self.assertTrue((target / "blobs" / f"sha256-{demo_layer}").exists())
            self.assertFalse((target / "blobs" / f"sha256-{other_layer}").exists())

            verified = self.run_cli("ollama", "verify", "demo", "--models-dir", str(target), env=env)
            self.assertIn(" - result: verified", verified.stdout)

    def test_apt_build_repo_and_activate_flow(self) -> None:
        with self.make_tempdir("ofpm-cli-apt-local-") as temp_dir:
            scenario_root = Path(temp_dir)
            repo_root = scenario_root / "zstd-repo"
            pool_dir = repo_root / "pool"

            source_path = scenario_root / "zstd.list"
            args_build = argparse.Namespace(
                package="zstd",
                version=None,
                distro="ubuntu",
                release="22.04",
                arch="amd64",
                output=str(repo_root),
            )
            args_activate = argparse.Namespace(
                path=str(repo_root),
                source_name=None,
                source_path=str(source_path),
                no_update=False,
            )
            args_deactivate = argparse.Namespace(
                path=str(repo_root),
                recursive=False,
                source_name=None,
                source_path=str(source_path),
                no_update=True,
            )

            def fake_live(cmd, **kwargs):
                if cmd[:2] == ["dpkg-scanpackages", "pool"]:
                    return subprocess.CompletedProcess(cmd, 0, stdout="Package: zstd\nVersion: 1.0.0\n\n", stderr="")
                if cmd[0] == "apt-get":
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                raise AssertionError(f"unexpected command: {cmd}")

            def fake_download(output_dir: Path, package_name: str, version: str) -> Path:
                output_dir.mkdir(parents=True, exist_ok=True)
                deb_path = output_dir / f"{package_name}_{version}_amd64.deb"
                deb_path.write_bytes(b"fake-deb")
                return deb_path

            with mock.patch("ofpm.cli.apt_policy_version", return_value="1.0.0"):
                with mock.patch("ofpm.cli.apt_dependency_names", return_value=["libzstd1"]):
                    with mock.patch("ofpm.cli.apt_download_package", side_effect=fake_download):
                        with mock.patch("ofpm.apt.run_command_live", side_effect=fake_live):
                            with mock.patch("ofpm.cli.run_command_live", side_effect=fake_live):
                                with mock.patch("ofpm.cli.apt_repo_access_issue", return_value=None):
                                    build_out = io.StringIO()
                                    with contextlib.redirect_stdout(build_out):
                                        result = cli.cmd_apt_build_repo(args_build)
                                    self.assertEqual(result, 0)
                                    self.assertIn("built apt local repo: zstd", build_out.getvalue())
                                    self.assertTrue((repo_root / "Packages").exists())
                                    self.assertTrue((repo_root / "Packages.gz").exists())
                                    self.assertTrue((pool_dir / "zstd_1.0.0_amd64.deb").exists())
                                    self.assertTrue((pool_dir / "libzstd1_1.0.0_amd64.deb").exists())

                                    activate_out = io.StringIO()
                                    with contextlib.redirect_stdout(activate_out):
                                        result = cli.cmd_apt_activate(args_activate)
                                    self.assertEqual(result, 0)
                                    self.assertIn("activated apt local repo: zstd-repo", activate_out.getvalue())
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

    def test_dnf_activate_and_deactivate_recursive(self) -> None:
        with self.make_tempdir("ofpm-cli-dnf-recursive-") as temp_dir:
            scenario_root = Path(temp_dir)
            repo_base = scenario_root / "rpm"
            first_repo = repo_base / "app1"
            second_repo = repo_base / "app2"
            for repo_root in (first_repo, second_repo):
                repodata = repo_root / "repodata"
                repodata.mkdir(parents=True, exist_ok=True)
                (repodata / "repomd.xml").write_text("<repomd/>", encoding="utf-8")

            repo_files_dir = scenario_root / "yum.repos.d"
            args_activate = argparse.Namespace(
                path=str(repo_base),
                recursive=True,
                repo_id=None,
                repo_file=str(repo_files_dir),
                no_refresh=True,
            )
            args_deactivate = argparse.Namespace(
                path=str(repo_base),
                recursive=True,
                repo_id=None,
                repo_file=str(repo_files_dir),
            )

            activate_out = io.StringIO()
            with contextlib.redirect_stdout(activate_out):
                result = cli.cmd_dnf_activate(args_activate)
            self.assertEqual(result, 0)
            created = sorted(path.name for path in repo_files_dir.glob("*.repo"))
            self.assertEqual(created, ["ofpm-app1.repo", "ofpm-app2.repo"])

            deactivate_out = io.StringIO()
            with contextlib.redirect_stdout(deactivate_out):
                result = cli.cmd_dnf_deactivate(args_deactivate)
            self.assertEqual(result, 0)
            self.assertEqual(list(repo_files_dir.glob("*.repo")), [])

    def test_apt_commands_helper_output(self) -> None:
        args = argparse.Namespace(
            package="zstd",
            version=None,
            output="/tmp/zstd-repo",
            source_name=None,
        )
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            result = cli.cmd_apt_commands(args)
        self.assertEqual(result, 0)
        output = captured.getvalue()
        self.assertIn("apt helper for: zstd", output)
        self.assertIn("ofpm apt build-repo zstd --output /tmp/zstd-repo", output)
        self.assertIn("sudo ofpm apt activate /tmp/zstd-repo --source-name ofpm-zstd", output)
        self.assertIn("sudo ofpm apt deactivate /tmp/zstd-repo --source-name ofpm-zstd", output)
        self.assertIn("dpkg -s zstd >/dev/null 2>&1 || sudo apt install zstd", output)

    def test_apt_commands_helper_defaults_output_to_current_directory(self) -> None:
        args = argparse.Namespace(
            package="zstd",
            version=None,
            output=None,
            source_name=None,
        )
        captured = io.StringIO()
        with mock.patch("pathlib.Path.cwd", return_value=Path("/tmp/current-repo")):
            with contextlib.redirect_stdout(captured):
                result = cli.cmd_apt_commands(args)
        self.assertEqual(result, 0)
        output = captured.getvalue()
        self.assertIn(" - output: /tmp/current-repo", output)
        self.assertIn("ofpm apt build-repo zstd", output)
        self.assertNotIn("--output", output)
        self.assertIn("sudo ofpm apt activate /tmp/current-repo --source-name ofpm-zstd", output)

    def test_apt_without_subcommand_prints_help_and_common_flow(self) -> None:
        with self.make_tempdir("ofpm-cli-apt-help-") as temp_dir:
            scenario_root = Path(temp_dir)
            env = self.scenario_env(scenario_root)
            result = subprocess.run(
                [sys.executable, "-m", "ofpm", "apt"],
                cwd=REPO_ROOT,
                env={**os.environ, **env, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("usage: ofpm apt", result.stdout)
            self.assertIn("ofpm apt build-repo zstd", result.stdout)
            self.assertIn("ofpm apt commands zstd", result.stdout)

    def test_invalid_subcommand_uses_readable_error(self) -> None:
        with self.make_tempdir("ofpm-cli-bad-command-") as temp_dir:
            scenario_root = Path(temp_dir)
            env = self.scenario_env(scenario_root)
            result = subprocess.run(
                [sys.executable, "-m", "ofpm", "apt", "nope"],
                cwd=REPO_ROOT,
                env={**os.environ, **env, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("ofpm apt: unable to parse command", result.stderr)
            self.assertIn("unknown command or value: nope", result.stderr)
            self.assertIn("available choices: list, show, commands", result.stderr)
            self.assertIn("help: ofpm apt -h", result.stderr)
            self.assertNotIn("invalid choice", result.stderr)

    def test_apt_list_and_show_inspect_local_repo_metadata(self) -> None:
        with self.make_tempdir("ofpm-cli-apt-show-") as temp_dir:
            scenario_root = Path(temp_dir)
            env = self.scenario_env(scenario_root)
            apt_repo = scenario_root / "apt" / "main" / "zstd"
            pool_dir = apt_repo / "pool"
            pool_dir.mkdir(parents=True, exist_ok=True)
            (apt_repo / "Packages").write_text(
                "\n".join(
                    [
                        "Package: zstd",
                        "Version: 1.0.0",
                        "Architecture: amd64",
                        "Filename: pool/zstd_1.0.0_amd64.deb",
                        "Size: 8",
                        "Description: fast compression tool",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (apt_repo / "Packages.gz").write_bytes(b"gz")
            (pool_dir / "zstd_1.0.0_amd64.deb").write_bytes(b"fake-deb")

            listed = self.run_cli("apt", "list", str(apt_repo), env=env)
            self.assertIn("apt local repo packages:", listed.stdout)
            self.assertIn("zstd 1.0.0 [arch=amd64] [file=pool/zstd_1.0.0_amd64.deb]", listed.stdout)

            recursive = self.run_cli("apt", "list", str(scenario_root / "apt"), "--recursive", env=env)
            self.assertIn("repo root count: 1", recursive.stdout)
            self.assertIn("package count: 1", recursive.stdout)

            shown = self.run_cli("apt", "show", "zstd", str(apt_repo), env=env)
            self.assertIn("apt package: zstd", shown.stdout)
            self.assertIn(" - version: 1.0.0", shown.stdout)
            self.assertIn(f" - repo root: {apt_repo}", shown.stdout)

    def test_apt_activate_and_deactivate_recursive(self) -> None:
        with self.make_tempdir("ofpm-cli-apt-recursive-") as temp_dir:
            scenario_root = Path(temp_dir)
            repo_base = scenario_root / "apt"
            first_repo = repo_base / "zstd" / "payload"
            second_repo = repo_base / "curl" / "payload"
            for repo_root in (first_repo, second_repo):
                pool_dir = repo_root / "pool"
                pool_dir.mkdir(parents=True, exist_ok=True)
                (repo_root / "Packages").write_text("Package: demo\nVersion: 1.0.0\n\n", encoding="utf-8")
                (repo_root / "Packages.gz").write_bytes(b"gz")

            sources_dir = scenario_root / "sources.list.d"
            args_activate = argparse.Namespace(
                path=str(repo_base),
                recursive=True,
                source_name=None,
                source_path=str(sources_dir),
                no_update=True,
            )
            args_deactivate = argparse.Namespace(
                path=str(repo_base),
                recursive=True,
                source_name=None,
                source_path=str(sources_dir),
                no_update=True,
            )

            activate_out = io.StringIO()
            with mock.patch("ofpm.cli.apt_repo_access_issue", return_value=None):
                with contextlib.redirect_stdout(activate_out):
                    result = cli.cmd_apt_activate(args_activate)
            self.assertEqual(result, 0)
            created = sorted(path.name for path in sources_dir.glob("*.list"))
            self.assertEqual(created, ["ofpm-curl_payload.list", "ofpm-zstd_payload.list"])

            deactivate_out = io.StringIO()
            with contextlib.redirect_stdout(deactivate_out):
                result = cli.cmd_apt_deactivate(args_deactivate)
            self.assertEqual(result, 0)
            self.assertEqual(list(sources_dir.glob("*.list")), [])

    def test_repo_query_uses_repos_config_and_repo_path(self) -> None:
        with self.make_tempdir("ofpm-cli-repo-query-") as temp_dir:
            scenario_root = Path(temp_dir)
            env = self.scenario_env(scenario_root)
            managed_root = scenario_root / "rootfs" / "home" / "tester" / ".ofpm"

            alpha_repo = scenario_root / "alpha-repo"
            beta_repo = scenario_root / "beta-repo"
            shutil.copytree(FIXTURE_REPO, alpha_repo)
            shutil.copytree(FIXTURE_REPO, beta_repo)

            alpha_manifest = alpha_repo / "ofpm" / "hello-tool" / "1.0.0" / "package.py"
            beta_manifest = beta_repo / "ofpm" / "hello-tool" / "1.0.0" / "package.py"
            alpha_data = cli.load_package_file(alpha_manifest)
            beta_data = cli.load_package_file(beta_manifest)
            alpha_data["metadata"]["description"] = "alpha fixture"
            beta_data["metadata"]["description"] = "beta fixture"
            cli.dump_package_file(alpha_manifest, alpha_data)
            cli.dump_package_file(beta_manifest, beta_data)

            repos_config = scenario_root / "repo-config.json"
            repos_config.write_text(
                json.dumps(
                    {
                        "alpha": str(alpha_repo / "ofpm"),
                        "beta": str(beta_repo),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            listed = self.run_cli("list", "--repos-config", str(repos_config), env=env)
            self.assertIn("[repo=alpha]", listed.stdout)
            self.assertIn("[repo=beta]", listed.stdout)

            shown = self.run_cli("show", "hello-tool", "--repos-config", str(repos_config), env=env)
            self.assertIn("matching packages for: hello-tool", shown.stdout)
            self.assertIn("[repo=alpha]", shown.stdout)
            self.assertIn("[repo=beta]", shown.stdout)

            selected = self.run_cli(
                "show",
                "hello-tool",
                "--repos-config",
                str(repos_config),
                "--repo",
                "beta",
                env=env,
            )
            self.assertIn("repo: beta", selected.stdout)
            self.assertIn("description: beta fixture", selected.stdout)

            direct = self.run_cli(
                "show",
                "hello-tool",
                "--repo-path",
                str(alpha_repo / "ofpm"),
                env=env,
            )
            self.assertIn("repo path: ", direct.stdout)
            self.assertIn("description: alpha fixture", direct.stdout)

            custom_native_root = scenario_root / "native-packages"
            shutil.copytree(alpha_repo / "ofpm", custom_native_root)
            custom = self.run_cli(
                "show",
                "hello-tool",
                "--repo-path",
                str(custom_native_root),
                env=env,
            )
            self.assertIn("repo path: ", custom.stdout)
            self.assertIn("description: alpha fixture", custom.stdout)

            installed = self.run_cli(
                "install",
                "hello-tool",
                "--repo-path",
                str(alpha_repo),
                "--root-path",
                str(managed_root),
                env=env,
            )
            self.assertIn("installed package: hello-tool 1.0.0", installed.stdout)

            ambiguous = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ofpm",
                    "install",
                    "hello-tool",
                    "--repos-config",
                    str(repos_config),
                    "--root-path",
                    str(managed_root),
                ],
                cwd=REPO_ROOT,
                env={**os.environ, **env, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(ambiguous.returncode, 0)
            self.assertIn("package is available from multiple repos: hello-tool", ambiguous.stdout)

    def test_install_ofpm_writes_launcher_profile_and_installed_source(self) -> None:
        with self.make_tempdir("ofpm-install-self-") as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "source"
            self.make_fake_ofpm_source(source_root)
            launcher_path = temp_root / "opt" / "ofpm" / "bin" / "ofpm"
            installed_source_root = temp_root / "opt" / "ofpm" / "src"
            profile_path = temp_root / "etc" / "profile.d" / "ofpm.sh"
            bashrc_path = temp_root / "etc" / "bash.bashrc"
            bashrc_path.parent.mkdir(parents=True, exist_ok=True)
            bashrc_path.write_text("# system bashrc\n", encoding="utf-8")

            args = argparse.Namespace(
                output=str(launcher_path),
                python="/usr/bin/python3",
                source_root=str(source_root),
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
            self.assertIn('export OFPM_MODE="installed"', launcher_text)
            self.assertIn(f'export OFPM_SOURCE_ROOT="{installed_source_root}"', launcher_text)
            self.assertIn(f'export OFPM_HOME="{temp_root / "opt" / "ofpm"}"', launcher_text)
            self.assertIn(f'export PYTHONPATH="{installed_source_root}${{PYTHONPATH:+:$PYTHONPATH}}"', launcher_text)
            self.assertTrue((installed_source_root / "ofpm" / "__main__.py").exists())
            self.assertFalse((installed_source_root / "tests").exists())
            self.assertFalse((installed_source_root / ".ai").exists())
            self.assertFalse((installed_source_root / "docker").exists())
            self.assertFalse((installed_source_root / "scripts").exists())
            self.assertFalse((installed_source_root / "repos").exists())
            self.assertTrue((temp_root / "opt" / "ofpm" / "repos" / "ofpm" / "main").exists())
            self.assertTrue((temp_root / "opt" / "ofpm" / "repos" / "ofpm" / "main" / "demo" / "1.0.0" / "package.py").exists())
            self.assertTrue((temp_root / "opt" / "ofpm" / "repos" / "ofpm" / "local-main").exists())
            self.assertFalse((temp_root / "opt" / "ofpm" / "repos" / "apt").exists())
            installed_repos_config = temp_root / "opt" / "ofpm" / "config" / "repos.json"
            self.assertTrue(installed_repos_config.exists())
            repos_data = json.loads(installed_repos_config.read_text(encoding="utf-8"))
            self.assertEqual(
                repos_data,
                {
                    "main": str((temp_root / "opt" / "ofpm" / "repos" / "ofpm" / "main").resolve()),
                    "local-main": str((temp_root / "opt" / "ofpm" / "repos" / "ofpm" / "local-main").resolve()),
                },
            )

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
            self.assertIn(f" - installed source root: {installed_source_root}", output)
            self.assertIn(f" - shell hook: {profile_path}", output)
            self.assertIn(f" - bashrc hook: {bashrc_path}", output)
            self.assertIn(" - command link: disabled", output)

    def test_install_ofpm_user_updates_single_bashrc_block(self) -> None:
        with self.make_tempdir("ofpm-install-user-") as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "source"
            self.make_fake_ofpm_source(source_root)
            home = temp_root / "home" / "tester"
            bashrc_path = home / ".bashrc"
            bashrc_path.parent.mkdir(parents=True, exist_ok=True)
            bashrc_path.write_text("# existing line\n", encoding="utf-8")
            launcher_path = home / ".ofpm" / "bin" / "ofpm"
            installed_source_root = home / ".ofpm" / "src"

            args = argparse.Namespace(
                output=str(launcher_path),
                python="/usr/bin/python3",
                source_root=str(source_root),
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
            self.assertTrue((installed_source_root / "ofpm" / "__main__.py").exists())
            self.assertTrue((home / ".ofpm" / "repos" / "ofpm" / "main").exists())

            second = io.StringIO()
            args.force = True
            with contextlib.redirect_stdout(second):
                result = cli.cmd_install_cli(args)
            self.assertEqual(result, 0)

            second_bashrc = bashrc_path.read_text(encoding="utf-8")
            self.assertEqual(second_bashrc.count("# >>> ofpm >>>"), 1)
            self.assertEqual(second_bashrc.count("# <<< ofpm <<<"), 1)

    def test_reinstall_ofpm_forces_replace(self) -> None:
        with self.make_tempdir("ofpm-reinstall-user-") as temp_dir:
            temp_root = Path(temp_dir)
            source_root = temp_root / "source"
            self.make_fake_ofpm_source(source_root)
            home = temp_root / "home" / "tester"
            bashrc_path = home / ".bashrc"
            bashrc_path.parent.mkdir(parents=True, exist_ok=True)
            launcher_path = home / ".ofpm" / "bin" / "ofpm"

            args = argparse.Namespace(
                output=str(launcher_path),
                python="/usr/bin/python3",
                source_root=str(source_root),
                root="user",
                profile_path=str(bashrc_path),
                bashrc_path=None,
                symlink_path=None,
                no_profile=False,
                no_symlink=False,
                force=False,
            )

            first = cli.cmd_install_cli(args)
            self.assertEqual(first, 0)
            second = cli.cmd_reinstall_cli(args)
            self.assertEqual(second, 0)
            self.assertTrue(launcher_path.exists())

    def test_reinstall_ofpm_prefers_current_checkout_over_installed_source_env(self) -> None:
        with self.make_tempdir("ofpm-reinstall-moved-source-") as temp_dir:
            temp_root = Path(temp_dir)
            old_installed_source = temp_root / "old-installed" / "src"
            moved_source = temp_root / "moved-source"
            self.make_fake_ofpm_source(old_installed_source)
            self.make_fake_ofpm_source(moved_source)
            (moved_source / "README.md").write_text("moved source tree\n", encoding="utf-8")

            home = temp_root / "home" / "tester"
            bashrc_path = home / ".bashrc"
            launcher_path = home / ".ofpm" / "bin" / "ofpm"

            args = argparse.Namespace(
                output=str(launcher_path),
                python="/usr/bin/python3",
                source_root=None,
                root="user",
                profile_path=str(bashrc_path),
                bashrc_path=None,
                symlink_path=None,
                no_profile=False,
                no_symlink=False,
                force=False,
            )

            with mock.patch.dict(os.environ, {"OFPM_SOURCE_ROOT": str(old_installed_source)}):
                with mock.patch("pathlib.Path.cwd", return_value=moved_source):
                    result = cli.cmd_reinstall_cli(args)

            self.assertEqual(result, 0)
            installed_readme = home / ".ofpm" / "src" / "README.md"
            self.assertEqual(installed_readme.read_text(encoding="utf-8"), "moved source tree\n")

            repos_config = home / ".ofpm" / "config" / "repos.json"
            repos_data = json.loads(repos_config.read_text(encoding="utf-8"))
            self.assertEqual(
                repos_data,
                {
                    "main": str((home / ".ofpm" / "repos" / "ofpm" / "main").resolve()),
                    "local-main": str((home / ".ofpm" / "repos" / "ofpm" / "local-main").resolve()),
                },
            )

    def test_prepare_list_shows_supported_preparers(self) -> None:
        result = self.run_cli("prepare", "list")
        self.assertIn("ollama", result.stdout)
        self.assertIn("ollama-runtime", result.stdout)
        self.assertIn("pi-agent", result.stdout)

    def test_prepare_ollama_imports_runtime_package_into_repo(self) -> None:
        with self.make_tempdir("ofpm-prepare-ollama-") as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repo"
            work_root = temp_root / "work"

            def fake_fetch(url: str):
                if url.endswith("/releases"):
                    return [{"tag_name": "v0.30.8", "draft": False}]
                if url.endswith("/releases/latest"):
                    return {"tag_name": "v0.30.8"}
                if url.endswith("/releases/tags/v0.30.8"):
                    return {
                        "assets": [
                            {
                                "name": "ollama-linux-amd64.tar.zst",
                                "browser_download_url": "https://example.invalid/ollama-linux-amd64.tar.zst",
                            }
                        ]
                    }
                raise AssertionError(url)

            def fake_download(url: str, path: Path) -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake ollama archive\n")

            preparer = get_preparer("ollama")
            versions = preparer.list_versions(fetch_json=fake_fetch)
            self.assertEqual(versions, ["0.30.8"])
            prepared = preparer.prepare(
                "latest",
                repo_dir=repo_root,
                work_dir=work_root,
                fetch_json=fake_fetch,
                download_file=fake_download,
            )

            dest = native_repo_package_root(repo_root) / "ollama-runtime" / "0.30.8"
            self.assertEqual(prepared.repo_package_root, dest)
            self.assertTrue((dest / "package.py").exists())
            self.assertTrue((dest / "payload" / "ollama-linux-amd64.tar.zst").exists())

    def test_prepare_pi_agent_imports_npm_bundle_into_repo(self) -> None:
        with self.make_tempdir("ofpm-prepare-pi-agent-") as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repo"
            work_root = temp_root / "work"

            def fake_fetch(url: str):
                return {
                    "dist-tags": {"latest": "1.2.3"},
                    "versions": {"1.2.2": {}, "1.2.3": {}},
                }

            def fake_run(command: list[str]) -> None:
                prefix = Path(command[command.index("--prefix") + 1])
                cli_path = prefix / "node_modules" / "@earendil-works" / "pi-coding-agent" / "dist" / "cli.js"
                cli_path.parent.mkdir(parents=True, exist_ok=True)
                cli_path.write_text("console.log('pi')\n", encoding="utf-8")

            preparer = get_preparer("pi-agent")
            versions = preparer.list_versions(fetch_json=fake_fetch)
            self.assertEqual(versions, ["1.2.3", "1.2.2"])
            prepared = preparer.prepare(
                "latest",
                repo_dir=repo_root,
                work_dir=work_root,
                fetch_json=fake_fetch,
                run_command=fake_run,
            )

            dest = native_repo_package_root(repo_root) / "pi-agent" / "1.2.3"
            self.assertEqual(prepared.repo_package_root, dest)
            self.assertTrue((dest / "package.py").exists())
            self.assertTrue((dest / "payload" / "pi-agent-1.2.3.tar.gz").exists())

    def test_system_ownership_normalization_chowns_tree_and_symlinks(self) -> None:
        with self.make_tempdir("ofpm-system-ownership-") as temp_dir:
            root = Path(temp_dir) / "payload"
            nested = root / "nested"
            nested.mkdir(parents=True)
            file_path = nested / "file.txt"
            file_path.write_text("payload\n", encoding="utf-8")
            link_path = root / "current"
            link_path.symlink_to(nested)

            from ofpm.runtime_support import normalize_system_ownership

            with mock.patch("os.geteuid", return_value=0):
                with mock.patch("os.chown") as chown_mock, mock.patch("os.lchown") as lchown_mock:
                    normalize_system_ownership(root, root_kind="system")

            chowned_paths = {Path(call.args[0]) for call in chown_mock.call_args_list}
            self.assertIn(root, chowned_paths)
            self.assertIn(nested, chowned_paths)
            self.assertIn(file_path, chowned_paths)
            lchowned_paths = {Path(call.args[0]) for call in lchown_mock.call_args_list}
            self.assertIn(link_path, lchowned_paths)


if __name__ == "__main__":
    unittest.main()
