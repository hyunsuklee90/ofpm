from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from ofpm.core import (
    apply_bundle,
    archive_export_bundle_dir,
    build_export_manifest,
    build_full_bundle_manifest,
    build_patch_bundle_manifest,
    find_installed_state,
    find_package_manifest,
    install_node_runtime,
    install_ollama_model_bundle,
    install_ollama_runtime,
    install_pi_agent,
    installed_states,
    list_available_packages,
    load_artifact_roots,
    load_bundle_archive,
    load_json,
    materialize_export_bundle_dir,
    managed_state_root,
    package_summary_from_manifest,
    repo_repos_config_path,
    remove_managed_payload,
    remove_node_runtime,
    registered_repos,
    resolve_package_specs,
    save_repos_config,
    user_repos_config_path,
    verify_package_sources,
    verify_node_runtime_install,
    verify_ollama_model_install,
    verify_ollama_runtime_install,
    verify_pi_agent_install,
    verify_state,
    write_bundle_archive,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def managed_root(root_kind: str) -> Path:
    if root_kind == "system":
        return Path("/opt/ofpm")
    if root_kind == "user":
        home = Path(os.environ.get("HOME", "~")).expanduser()
        return home / ".ofpm"
    raise ValueError(f"unsupported root kind: {root_kind}")


def effective_managed_root(args: argparse.Namespace) -> Path:
    if getattr(args, "root_path", None):
        return Path(args.root_path).resolve()
    return managed_root(getattr(args, "root", "user"))


def effective_artifact_roots() -> dict[str, str]:
    return load_artifact_roots(repo_root())


def available_packages_with_repo() -> list[dict[str, object]]:
    root = repo_root()
    artifact_roots = effective_artifact_roots()
    repos = registered_repos(root)
    if not repos:
        repos = {"main": str(root)}

    packages: list[dict[str, object]] = []
    for repo_id, repo_path_raw in sorted(repos.items()):
        repo_path = Path(repo_path_raw).expanduser().resolve()
        catalog_root = repo_path / "catalog"
        if not catalog_root.exists():
            continue
        for item in list_available_packages(catalog_root, artifact_roots):
            package = dict(item)
            package["repo_id"] = repo_id
            package["repo_path"] = str(repo_path)
            packages.append(package)
    return sorted(
        packages,
        key=lambda item: (
            str(item["package_id"]),
            str(item["version"]),
            str(item["repo_id"]),
        ),
    )


def offline_strict_enabled() -> bool:
    value = os.environ.get("OFPM_OFFLINE_STRICT", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def require_offline_target_mode(command_name: str) -> None:
    if not offline_strict_enabled():
        print(f"warning: {command_name} is running with OFPM_OFFLINE_STRICT=0")
        print("warning: target-side commands are intended to remain offline-only")


def cmd_init(args: argparse.Namespace) -> int:
    root = repo_root()
    for rel in [
        "schemas",
        "profiles",
        "catalog/packages",
        "store/blobs/sha256",
        "dist",
        "runtime/targets",
        "runtime/state",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    print(f"initialized scaffold under {root}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    if args.installed:
        state_root = managed_state_root(effective_managed_root(args))
        installed = installed_states(state_root)
        if args.pattern:
            installed = [
                item
                for item in installed
                if args.pattern.lower() in item["package_id"].lower()
            ]
        if args.json:
            print_json({"installed": installed})
            return 0
        if not installed:
            print(f"no installed packages recorded under {state_root}")
            return 0
        print(f"state root: {state_root}")
        print(f"installed package count: {len(installed)}")
        for item in installed:
            print(
                " - "
                f"{item['package_id']} {item['package_version']} "
                f"[profile={item['profile_id']}] "
                f"[install_root={item['install_root']}] "
                f"[tracked_files={item['tracked_file_count']}]"
            )
            if args.verbose:
                print(f"   state: {item['state_path']}")
                print(f"   bundle: {item['bundle_id']} ({item['bundle_type']})")
        return 0

    available = available_packages_with_repo()
    if not args.all:
        available = [item for item in available if item.get("available", True)]
    if args.pattern:
        available = [
            item
            for item in available
            if args.pattern.lower() in item["package_id"].lower()
        ]
    if args.json:
        print_json({"packages": available})
        return 0

    if not available:
        print("no packages found in registered repos")
        return 0

    print("package sources: registered repos")
    print(f"package count: {len(available)}")
    for package in available:
        print(
            " - "
            f"{package['package_id']} {package['version']} "
            f"[repo={package['repo_id']}] "
            f"[profile={package['profile_id']}] "
            f"[install_root={package['install_root']}] "
            f"[files={package['file_count']}] "
            f"[available={'yes' if package.get('available', True) else 'no'}]"
        )
        if args.verbose:
            if package["description"]:
                print(f"   description: {package['description']}")
            print(f"   repo path: {package['repo_path']}")
            print(f"   manifest: {package['manifest']}")
            if package.get("availability_error"):
                print(f"   availability error: {package['availability_error']}")
            if not package.get("available", True):
                print(f"   missing sources: {package.get('missing_count', 0)}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    root = repo_root()
    artifact_roots = effective_artifact_roots()
    manifest_path = find_package_manifest(root / "catalog", args.package, args.version)
    if manifest_path is None:
        print(f"package not found: {args.package}")
        return 1
    package = package_summary_from_manifest(
        manifest_path,
        include_files=args.files,
        artifact_roots=artifact_roots,
    )
    installed = find_installed_state(managed_state_root(effective_managed_root(args)), package["package_id"])

    if args.json:
        print_json({"package": package, "installed": installed})
        return 0

    print(f"package: {package['package_id']}")
    print(f"version: {package['version']}")
    print(f"profile: {package['profile_id']}")
    print(f"install root: {package['install_root']}")
    print(f"manifest: {package['manifest']}")
    if package["description"]:
        print(f"description: {package['description']}")
    print(f"file count: {package['file_count']}")
    print(f"available: {'yes' if package['available'] else 'no'}")
    if package.get("availability_error"):
        print(f"availability error: {package['availability_error']}")
    if package["missing_count"]:
        print(f"missing sources: {package['missing_count']}")
    if package["depends"]:
        print("dependencies:")
        for dep in package["depends"]:
            dep_version = dep.get("version", "*")
            dep_required = "required" if dep.get("required", True) else "optional"
            line = f" - {dep['package_id']} {dep_version} [{dep_required}]"
            if dep.get("reason"):
                line += f" {dep['reason']}"
            print(line)
    if installed:
        print("installed: yes")
        print(f"installed version: {installed['package_version']}")
        print(f"installed state: {installed['state_path']}")
        print(f"installed bundle: {installed['bundle_id']} ({installed['bundle_type']})")
    else:
        print("installed: no")

    if package["missing_count"]:
        print("missing artifact sources:")
        for source in package["missing_sources"][:20]:
            print(f" - {source}")
        if package["missing_count"] > 20:
            print(f" - ... {package['missing_count'] - 20} more")

    if args.files:
        print("files:")
        for file_item in package["files"]:
            print(f" - {file_item['target']} <= {file_item['source']}")
    return 0


def cmd_verify_source(args: argparse.Namespace) -> int:
    root = repo_root()
    manifest_path = find_package_manifest(root / "catalog", args.package, args.version)
    if manifest_path is None:
        print(f"package not found: {args.package}")
        return 1
    result = verify_package_sources(
        manifest_path,
        artifact_roots=effective_artifact_roots(),
    )
    print(f"verify-source package: {result['package_id']}")
    print(f" - version: {result['version']}")
    print(f" - manifest: {result['manifest']}")
    print(f" - declared source paths: {result['declared_source_count']}")
    print(f" - expanded files: {result['expanded_file_count']}")
    if result["missing_sources"]:
        print(f" - missing source paths: {len(result['missing_sources'])}")
        for path in result["missing_sources"][:20]:
            print(f"   {path}")
        if len(result["missing_sources"]) > 20:
            print(f"   ... {len(result['missing_sources']) - 20} more")
    if result["missing_files"]:
        print(f" - missing expanded files: {len(result['missing_files'])}")
        for path in result["missing_files"][:20]:
            print(f"   {path}")
        if len(result["missing_files"]) > 20:
            print(f"   ... {len(result['missing_files']) - 20} more")
    if result["ok"]:
        print(" - result: verified")
        return 0
    print(" - result: failed")
    return 1


def cmd_install(args: argparse.Namespace) -> int:
    require_offline_target_mode("install")
    root = repo_root()
    artifact_roots = effective_artifact_roots()
    manifest_path = find_package_manifest(root / "catalog", args.package, args.version)
    if manifest_path is None:
        print(f"package not found: {args.package}")
        return 1
    package = package_summary_from_manifest(manifest_path, artifact_roots=artifact_roots)
    managed = effective_managed_root(args)
    package_data = load_json(manifest_path)
    if package["package_id"] == "node-runtime":
        state = install_node_runtime(
            managed,
            manifest_path,
            package_data,
            root_kind=args.root,
            artifact_roots=artifact_roots,
        )
        print(f"installed package: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(f" - current path: {state['package']['current_path']}")
        print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
        return 0
    if package["package_id"] == "ollama-runtime":
        state = install_ollama_runtime(
            managed,
            manifest_path,
            package_data,
            root_kind=args.root,
            artifact_roots=artifact_roots,
        )
        print(f"installed package: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(f" - current path: {state['package']['current_path']}")
        print(f" - library dir: {state['package']['library_dir']}")
        print(f" - install mode: {state['package']['install_mode']}")
        print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
        return 0
    if package["package_id"] == "pi-agent":
        state = install_pi_agent(
            managed,
            manifest_path,
            package_data,
            root_kind=args.root,
            artifact_roots=artifact_roots,
        )
        print(f"installed package: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(f" - current path: {state['package']['current_path']}")
        print(f" - config dir: {state['package']['config_dir']}")
        print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
        return 0
    if package["package_id"].startswith("ollama-model-"):
        state = install_ollama_model_bundle(
            managed,
            manifest_path,
            package_data,
            root_kind=args.root,
            artifact_roots=artifact_roots,
        )
        print(f"installed package: {package['package_id']} {package['version']}")
        print(f" - managed root: {managed}")
        print(f" - current path: {state['package']['current_path']}")
        print(f" - models path: {state['package']['models_path']}")
        print(f" - state file: {managed_state_root(managed) / (package['package_id'] + '.json')}")
        return 0
    print(f"install plan for {package['package_id']} {package['version']}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    print(f" - managed root: {managed}")
    print(f" - check catalog manifest: {package['manifest']}")
    print(f" - check target profile compatibility: expected {package['profile_id']}")
    print(f" - install root policy: {package['install_root']}")
    print(f" - package file count: {package['file_count']}")
    print(" - action: full install planning only for now")
    print("next implementation: resolve target profile, build/apply bundle, and record installed state")
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    require_offline_target_mode("upgrade")
    root = repo_root()
    installed = find_installed_state(managed_state_root(effective_managed_root(args)), args.package)
    manifest_path = find_package_manifest(root / "catalog", args.package, args.version)
    if manifest_path is None:
        print(f"package not found: {args.package}")
        return 1
    package = package_summary_from_manifest(manifest_path, artifact_roots=effective_artifact_roots())
    print(f"upgrade plan for {package['package_id']}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    if installed:
        print(f" - installed version: {installed['package_version']}")
        print(f" - installed state: {installed['state_path']}")
    else:
        print(" - installed version: not recorded")
    print(f" - target version: {package['version']}")
    print(f" - target profile: {package['profile_id']}")
    print(" - action: patch/full decision planning only for now")
    print("next implementation: compare lineage and choose patch or full bundle")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    require_offline_target_mode("remove")
    root = repo_root()
    managed = effective_managed_root(args)
    installed = find_installed_state(managed_state_root(managed), args.package)
    if installed is None:
        print(f"package not installed: {args.package}")
        return 1
    if installed["package_id"] == "node-runtime":
        result = remove_node_runtime(managed, installed)
        print(f"removed package: {result['package_id']} {result['package_version']}")
        print(f" - managed root: {result['managed_root']}")
        print(f" - removed version root: {result['removed_version_root']}")
        return 0
    if installed["package_id"] in {"ollama-runtime", "pi-agent"} or installed["package_id"].startswith("ollama-model-"):
        result = remove_managed_payload(managed, installed)
        print(f"removed package: {result['package_id']} {result['package_version']}")
        print(f" - managed root: {result['managed_root']}")
        print(f" - removed version root: {result['removed_version_root']}")
        return 0
    print(f"remove plan for {args.package}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    print(f" - installed version: {installed['package_version']}")
    print(f" - install root: {installed['install_root']}")
    print(f" - tracked files: {installed['tracked_file_count']}")
    print(f" - state file: {installed['state_path']}")
    print(" - action: removal planning only for now")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    require_offline_target_mode("verify")
    managed = effective_managed_root(args)
    installed = find_installed_state(managed_state_root(managed), args.package)
    if installed is None:
        print(f"package not installed: {args.package}")
        return 1
    if installed["package_id"] == "node-runtime":
        errors = verify_node_runtime_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if installed["package_id"] == "ollama-runtime":
        errors = verify_ollama_runtime_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if installed["package_id"] == "pi-agent":
        errors = verify_pi_agent_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if installed["package_id"].startswith("ollama-model-"):
        errors = verify_ollama_model_install(installed)
        print(f"verify package: {args.package}")
        print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
        print(f" - managed root: {managed}")
        print(f" - state file: {installed['state_path']}")
        if errors:
            print(" - result: failed")
            for error in errors:
                print(f"   {error}")
            return 1
        print(" - result: verified")
        return 0
    if not args.target_root:
        print("verify requires --target-root for this package type")
        return 1
    target_root = Path(args.target_root).resolve()
    errors = verify_state(
        target_root.resolve(),
        Path(installed["state_path"]).resolve(),
        check_modes=args.strict_modes,
    )
    print(f"verify package: {args.package}")
    print(f" - network policy: offline-strict={'on' if offline_strict_enabled() else 'off'}")
    print(f" - state file: {installed['state_path']}")
    print(f" - target root: {target_root.resolve()}")
    print(f" - tracked files: {installed['tracked_file_count']}")
    if errors:
        print(" - result: failed")
        for error in errors:
            print(f"   {error}")
        return 1
    print(" - result: verified")
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    managed = effective_managed_root(args)
    installed = installed_states(managed_state_root(managed))
    if args.json:
        print_json({"installed": installed})
        return 0
    if not installed:
        print(f"no installed packages recorded under {managed_state_root(managed)}")
        return 0
    print(f"managed root: {managed}")
    print(f"state root: {managed_state_root(managed)}")
    print(f"installed package count: {len(installed)}")
    for item in installed:
        print(f" - {item['package_id']} {item['package_version']} [{item['updated_at']}]")
        print(f"   install_root: {item['install_root']}")
        print(f"   profile: {item['profile_id']}")
        print(f"   state: {item['state_path']}")
        print(f"   bundle: {item['bundle_id']} ({item['bundle_type']})")


def cmd_env(args: argparse.Namespace) -> int:
    root = effective_managed_root(args)
    bin_dir = root / "bin"
    ollama_lib_dir = root / "payloads" / "ollama-runtime" / "current" / "lib" / "ollama"
    ollama_models_dir = root / "data" / "ollama-models"
    pi_config_dir = root / "payloads" / "pi-agent" / "current" / "config" / "agent"
    payload_bin_dirs = [
        path
        for path in [
            root / "payloads" / "node-runtime" / "current" / "bin",
            root / "payloads" / "pi-agent" / "current" / "bin",
            root / "payloads" / "ollama-runtime" / "current" / "bin",
        ]
        if path.exists()
    ]
    path_entries = [path for path in [bin_dir, *payload_bin_dirs] if path.exists()]

    export_lines = [f'export OFPM_ROOT="{root}"']
    if path_entries:
        export_lines.append(f'export PATH="{":".join(str(path) for path in path_entries)}:$PATH"')
    export_lines.append(f'export PI_CODING_AGENT_DIR="{pi_config_dir}"')
    if ollama_lib_dir.exists():
        export_lines.append(f'export OLLAMA_LIBRARY_PATH="{ollama_lib_dir}"')
        export_lines.append(f'export LD_LIBRARY_PATH="{ollama_lib_dir}:$LD_LIBRARY_PATH"')
    export_lines.append(f'export OLLAMA_MODELS="{ollama_models_dir}"')

    if args.export:
        for line in export_lines:
            print(line)
        return 0

    print(f"root kind: {args.root}")
    print(f"managed root: {root}")
    print("path entries:")
    for entry in path_entries:
        print(f" - {entry}")
    print("shell snippet:")
    for line in export_lines:
        print(f"  {line}")
    print("usage:")
    print(f" - one-shot: eval \"$(./bin/ofpm env --root {args.root} --export)\"")
    print(f" - inspect only: ./bin/ofpm env --root {args.root}")
    print("notes:")
    print(" - this does not modify your shell automatically")
    print(" - edit the snippet before adding it to ~/.bashrc if you want a different PATH order")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    print("note: 'sources' is a compatibility view; prefer 'ofpm repo list'")
    roots = effective_artifact_roots()
    if args.json:
        print_json({"artifact_roots": roots})
        return 0
    if not roots:
        print("no artifact roots configured")
        print(f"user repos config: {user_repos_config_path()}")
        print(f"repo repos config: {repo_repos_config_path(repo_root())}")
        return 0
    print("configured artifact roots:")
    for root_id, path in sorted(roots.items()):
        print(f" - {root_id}: {path}")
    print(f"user repos config: {user_repos_config_path()}")
    print(f"repo repos config: {repo_repos_config_path(repo_root())}")
    return 0


def repo_config_path(args: argparse.Namespace) -> Path:
    if args.scope == "user":
        return user_repos_config_path()
    if args.scope == "repo":
        return repo_repos_config_path(repo_root())
    raise ValueError(f"unsupported repo scope: {args.scope}")


def stored_repos(args: argparse.Namespace) -> dict[str, str]:
    path = repo_config_path(args)
    if not path.exists():
        return {}
    return load_json(path)


def cmd_repo_list(args: argparse.Namespace) -> int:
    path = repo_config_path(args)
    repos = stored_repos(args)
    if args.json:
        print_json({"scope": args.scope, "config_path": str(path), "repos": repos})
        return 0
    if not repos:
        print(f"no registered repos in {path}")
        return 0
    print(f"repo scope: {args.scope}")
    print(f"config path: {path}")
    print("registered repos:")
    for repo_id, repo_path in sorted(repos.items()):
        print(f" - {repo_id}: {repo_path}")
    return 0


def cmd_repo_add(args: argparse.Namespace) -> int:
    path = repo_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    repo_path = str(Path(args.path).expanduser().resolve())
    repos[repo_id] = repo_path
    save_repos_config(path, repos)
    print(f"registered repo: {repo_id}")
    print(f" - path: {repo_path}")
    print(f" - scope: {args.scope}")
    print(f" - config: {path}")
    return 0


def cmd_repo_remove(args: argparse.Namespace) -> int:
    path = repo_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    if repo_id not in repos:
        print(f"repo not found: {repo_id}")
        print(f" - scope: {args.scope}")
        print(f" - config: {path}")
        return 1
    removed_path = repos.pop(repo_id)
    save_repos_config(path, repos)
    print(f"removed repo: {repo_id}")
    print(f" - path: {removed_path}")
    print(f" - scope: {args.scope}")
    print(f" - config: {path}")
    return 0


def cmd_repo_show(args: argparse.Namespace) -> int:
    path = repo_config_path(args)
    repos = stored_repos(args)
    repo_id = args.repo_id.strip().lower()
    if repo_id not in repos:
        print(f"repo not found: {repo_id}")
        print(f" - scope: {args.scope}")
        print(f" - config: {path}")
        return 1
    print(f"repo: {repo_id}")
    print(f" - path: {repos[repo_id]}")
    print(f" - scope: {args.scope}")
    print(f" - config: {path}")
    return 0


def cmd_fetch_apt(args: argparse.Namespace) -> int:
    print("fetch plan: apt")
    print(f" - package: {args.package}")
    print(f" - distro: {args.distro}")
    print(f" - release: {args.release}")
    print(f" - arch: {args.arch}")
    print(f" - include dependencies: {'yes' if args.with_deps else 'no'}")
    print(f" - output dir: {Path(args.output).resolve()}")
    print(" - mode: builder-side online acquisition")
    print(" - target policy: fetched artifacts must be installable later without network access")
    print("next implementation:")
    print(" - resolve package metadata from apt sources for the selected distro/release")
    print(" - download .deb payloads and dependency closure")
    print(" - record source metadata and checksums in ofpm catalog form")
    print(" - emit a local repo snapshot or artifact bundle for offline install")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    root = repo_root()
    package_entries = resolve_package_specs(
        root / "catalog",
        args.package,
        artifact_roots=effective_artifact_roots(),
    )
    bundle_manifest = build_export_manifest(args.name, package_entries)
    output_root = Path(args.output).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    bundle_root = materialize_export_bundle_dir(output_root, bundle_manifest)
    if args.format == "dir":
        print(f"exported bundle dir: {bundle_root}")
        print(f"bundle manifest: {bundle_root / 'bundle.json'}")
        return 0

    archive_path = archive_export_bundle_dir(bundle_root)
    if not args.keep_dir:
        shutil.rmtree(bundle_root)
        print(f"exported bundle archive: {archive_path}")
        print(f"bundle dir removed after archiving: {bundle_root}")
    else:
        print(f"exported bundle dir: {bundle_root}")
        print(f"exported bundle archive: {archive_path}")
    return 0


def cmd_pack_full(args: argparse.Namespace) -> int:
    root = repo_root()
    package_manifest = Path(args.package).resolve()
    package_data = load_json(package_manifest)
    bundle_manifest = build_full_bundle_manifest(
        package_data,
        package_manifest,
        root / "store",
        artifact_roots=effective_artifact_roots(),
    )
    archive = write_bundle_archive(bundle_manifest, root / "store", root / "dist")
    print(archive)
    return 0


def cmd_pack_patch(args: argparse.Namespace) -> int:
    root = repo_root()
    from_manifest = Path(args.from_package).resolve()
    to_manifest = Path(args.to_package).resolve()
    from_data = load_json(from_manifest)
    to_data = load_json(to_manifest)
    bundle_manifest = build_patch_bundle_manifest(
        from_data,
        from_manifest,
        to_data,
        to_manifest,
        root / "store",
        artifact_roots=effective_artifact_roots(),
    )
    archive = write_bundle_archive(bundle_manifest, root / "store", root / "dist")
    print(archive)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    bundle_path = Path(args.bundle).resolve()
    target_root = Path(args.target_root).resolve()
    state_path = Path(args.state).resolve()
    bundle_manifest, temp_dir, extracted_root = load_bundle_archive(bundle_path)
    try:
        state = apply_bundle(bundle_manifest, extracted_root, target_root, state_path)
    finally:
        temp_dir.cleanup()
    print(state_path)
    print(f"applied {state['bundle']['bundle_id']}")
    return 0


def cmd_verify_state(args: argparse.Namespace) -> int:
    errors = verify_state(
        Path(args.target_root).resolve(),
        Path(args.state).resolve(),
        check_modes=args.strict_modes,
    )
    if errors:
        for error in errors:
            print(error)
        return 1
    print("state verified")
    return 0


def cmd_show_manifest(args: argparse.Namespace) -> int:
    bundle_manifest, temp_dir, _ = load_bundle_archive(Path(args.bundle).resolve())
    try:
        print_json(bundle_manifest)
    finally:
        temp_dir.cleanup()
    return 0


def print_json(data: dict) -> None:
    import json

    print(json.dumps(data, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ofpm")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_root_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--root", choices=["system", "user"], default="user")
        command_parser.add_argument("--root-path")

    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(func=cmd_init)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("pattern", nargs="?")
    list_parser.add_argument("--installed", action="store_true")
    list_parser.add_argument("--all", action="store_true")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--verbose", action="store_true")
    add_root_options(list_parser)
    list_parser.set_defaults(func=cmd_list)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("package")
    show_parser.add_argument("--version")
    show_parser.add_argument("--files", action="store_true")
    show_parser.add_argument("--json", action="store_true")
    add_root_options(show_parser)
    show_parser.set_defaults(func=cmd_show)

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("package")
    install_parser.add_argument("--version")
    add_root_options(install_parser)
    install_parser.set_defaults(func=cmd_install)

    upgrade_parser = subparsers.add_parser("upgrade")
    upgrade_parser.add_argument("package")
    upgrade_parser.add_argument("--version")
    add_root_options(upgrade_parser)
    upgrade_parser.set_defaults(func=cmd_upgrade)

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("package")
    add_root_options(remove_parser)
    remove_parser.set_defaults(func=cmd_remove)

    verify_pkg_parser = subparsers.add_parser("verify")
    verify_pkg_parser.add_argument("package")
    verify_pkg_parser.add_argument("--target-root")
    verify_pkg_parser.add_argument("--strict-modes", action="store_true")
    add_root_options(verify_pkg_parser)
    verify_pkg_parser.set_defaults(func=cmd_verify)

    verify_source_parser = subparsers.add_parser("verify-source")
    verify_source_parser.add_argument("package")
    verify_source_parser.add_argument("--version")
    verify_source_parser.set_defaults(func=cmd_verify_source)

    state_parser = subparsers.add_parser("state")
    state_parser.add_argument("--json", action="store_true")
    add_root_options(state_parser)
    state_parser.set_defaults(func=cmd_state)

    env_parser = subparsers.add_parser("env")
    env_parser.add_argument("--root", choices=["system", "user"], default="user")
    env_parser.add_argument("--root-path")
    env_parser.add_argument("--export", action="store_true")
    env_parser.set_defaults(func=cmd_env)

    sources_parser = subparsers.add_parser("sources")
    sources_parser.add_argument("--json", action="store_true")
    sources_parser.set_defaults(func=cmd_sources)

    repo_parser = subparsers.add_parser("repo")
    repo_subparsers = repo_parser.add_subparsers(dest="repo_command", required=True)

    repo_list_parser = repo_subparsers.add_parser("list")
    repo_list_parser.add_argument("--scope", choices=["user", "repo"], default="user")
    repo_list_parser.add_argument("--json", action="store_true")
    repo_list_parser.set_defaults(func=cmd_repo_list)

    repo_add_parser = repo_subparsers.add_parser("add")
    repo_add_parser.add_argument("repo_id")
    repo_add_parser.add_argument("path")
    repo_add_parser.add_argument("--scope", choices=["user", "repo"], default="user")
    repo_add_parser.set_defaults(func=cmd_repo_add)

    repo_remove_parser = repo_subparsers.add_parser("remove")
    repo_remove_parser.add_argument("repo_id")
    repo_remove_parser.add_argument("--scope", choices=["user", "repo"], default="user")
    repo_remove_parser.set_defaults(func=cmd_repo_remove)

    repo_show_parser = repo_subparsers.add_parser("show")
    repo_show_parser.add_argument("repo_id")
    repo_show_parser.add_argument("--scope", choices=["user", "repo"], default="user")
    repo_show_parser.set_defaults(func=cmd_repo_show)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("name")
    export_parser.add_argument("--package", action="append", required=True)
    export_parser.add_argument("--format", choices=["dir", "tar.gz"], default="dir")
    export_parser.add_argument("--output", default="exports")
    export_parser.add_argument("--keep-dir", action="store_true")
    export_parser.set_defaults(func=cmd_export)

    fetch_parser = subparsers.add_parser("fetch")
    fetch_subparsers = fetch_parser.add_subparsers(dest="fetch_command", required=True)

    fetch_apt_parser = fetch_subparsers.add_parser("apt")
    fetch_apt_parser.add_argument("package")
    fetch_apt_parser.add_argument("--distro", default="ubuntu")
    fetch_apt_parser.add_argument("--release", default="22.04")
    fetch_apt_parser.add_argument("--arch", default="amd64")
    fetch_apt_parser.add_argument("--output", default="incoming/apt")
    fetch_apt_parser.add_argument("--with-deps", action="store_true")
    fetch_apt_parser.set_defaults(func=cmd_fetch_apt)

    full_parser = subparsers.add_parser("pack-full")
    full_parser.add_argument("--package", required=True)
    full_parser.set_defaults(func=cmd_pack_full)

    patch_parser = subparsers.add_parser("pack-patch")
    patch_parser.add_argument("--from-package", required=True)
    patch_parser.add_argument("--to-package", required=True)
    patch_parser.set_defaults(func=cmd_pack_patch)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--bundle", required=True)
    apply_parser.add_argument("--target-root", required=True)
    apply_parser.add_argument("--state", required=True)
    apply_parser.set_defaults(func=cmd_apply)

    verify_parser = subparsers.add_parser("verify-state")
    verify_parser.add_argument("--target-root", required=True)
    verify_parser.add_argument("--state", required=True)
    verify_parser.add_argument("--strict-modes", action="store_true")
    verify_parser.set_defaults(func=cmd_verify_state)

    show_manifest_parser = subparsers.add_parser("show-manifest")
    show_manifest_parser.add_argument("--bundle", required=True)
    show_manifest_parser.set_defaults(func=cmd_show_manifest)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
