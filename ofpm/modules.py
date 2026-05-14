from __future__ import annotations

from pathlib import Path
from typing import Any


def _lua_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _module_header(package_id: str, version: str, description: str) -> list[str]:
    return [
        f"help([[ofpm managed package env: {package_id}@{version}]])",
        f"whatis([[Name : {package_id}]])",
        f"whatis([[Version : {version}]])",
        "whatis([[Category : ofpm managed package env]])",
        f"whatis([[Description : {description}]])",
        "",
    ]


def package_env_spec(state: dict[str, Any]) -> dict[str, Any]:
    package = state["package"]
    env_spec = package.get("env")
    if env_spec:
        return env_spec

    package_id = package["package_id"]
    if package_id == "node-runtime":
        return {"prepend_path": {"PATH": ["@package_root/bin"]}}
    if package_id == "ollama-runtime":
        return {
            "prepend_path": {
                "PATH": ["@package_root/bin"],
                "LD_LIBRARY_PATH": ["@library_dir"],
            },
            "set": {
                "OLLAMA_LIBRARY_PATH": "@library_dir",
            },
        }
    if package_id == "pi-agent":
        return {
            "prepend_path": {"PATH": ["@package_root/bin"]},
            "set": {"PI_CODING_AGENT_DIR": "@config_dir"},
        }
    if package_id.startswith("ollama-model-"):
        return {
            "set": {
                "OLLAMA_MODELS": "@managed_root/data/ollama-models",
            }
        }
    return {}


def _resolve_env_value(value: str, package: dict[str, Any], managed_root: Path) -> str:
    replacements = {
        "@managed_root": str(managed_root),
        "@package_root": package.get("current_path", ""),
        "@config_dir": package.get("config_dir", ""),
        "@library_dir": package.get("library_dir", ""),
        "@models_path": package.get("models_path", ""),
        "@prefix_root": package.get("prefix_root", ""),
    }
    for token, resolved in replacements.items():
        if value == token:
            return resolved
        prefix = token + "/"
        if value.startswith(prefix):
            suffix = value[len(prefix) :]
            if not resolved:
                return ""
            return str(Path(resolved) / suffix)
    return value


def resolved_package_env(managed_root: Path, state: dict[str, Any]) -> dict[str, dict[str, list[str] | str]]:
    package = state["package"]
    env_spec = package_env_spec(state)
    result: dict[str, dict[str, list[str] | str]] = {
        "set": {
            "OFPM_ROOT": str(managed_root),
        },
        "prepend_path": {},
    }

    for name, raw_value in env_spec.get("set", {}).items():
        resolved = _resolve_env_value(str(raw_value), package, managed_root)
        if resolved:
            result["set"][name] = resolved

    for name, raw_values in env_spec.get("prepend_path", {}).items():
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        resolved_values = [
            resolved
            for value in values
            if (resolved := _resolve_env_value(str(value), package, managed_root))
        ]
        if resolved_values:
            result["prepend_path"][name] = resolved_values

    return result


def render_package_modulefile(managed_root: Path, state: dict[str, Any]) -> str:
    package = state["package"]
    package_id = package["package_id"]
    version = package["package_version"]
    description = package.get("env_description") or package.get("description") or f"Environment for {package_id}."
    env_data = resolved_package_env(managed_root, state)
    lines = _module_header(package_id, version, description)
    lines.append(f"local root = {_lua_quote(str(managed_root))}")
    for name, value in sorted(env_data["set"].items()):
        lines.append(f"setenv({_lua_quote(name)}, {_lua_quote(str(value))})")
    for name, values in sorted(env_data["prepend_path"].items()):
        for value in values:
            lines.append(f"prepend_path({_lua_quote(name)}, {_lua_quote(str(value))})")
    return "\n".join(lines) + "\n"


def render_package_shell_env(managed_root: Path, state: dict[str, Any]) -> str:
    env_data = resolved_package_env(managed_root, state)
    lines: list[str] = []
    for name, value in sorted(env_data["set"].items()):
        lines.append(f"export {name}={_sh_quote(str(value))}")
    for name, values in sorted(env_data["prepend_path"].items()):
        for value in values:
            lines.append(f"export {name}={_sh_quote(str(value))}:${name}")
    return "\n".join(lines) + "\n"
