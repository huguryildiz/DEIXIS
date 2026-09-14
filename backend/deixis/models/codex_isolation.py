"""Launch overrides that remove user-level tools and instructions from DEIXIS Codex sessions.

Accepted overrides are not proof of isolation: unknown keys may be ignored. The
boundary probe checks observable behavior (tool events, loaded instruction
sources, MCP/skill listings) before the adapter is treated as ready.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "shell_snapshot",
    "apps",
    "plugins",
    "remote_plugin",
    "memories",
    "hooks",
    "browser_use",
    "browser_use_external",
    "in_app_browser",
    "computer_use",
    "image_generation",
    "view_image",
    "multi_agent",
    "goals",
    "skill_search",
    "skill_mcp_dependency_install",
    "tool_suggest",
    "sleep_tool",
    "workspace_dependencies",
)

BASE_OVERRIDES = (
    'approval_policy="never"',
    'sandbox_mode="read-only"',
    'web_search="disabled"',
    "project_doc_max_bytes=0",
    "skills.include_instructions=false",
    "skills.bundled.enabled=false",
    "include_permissions_instructions=false",
    "include_environment_context=false",
    "include_apps_instructions=false",
    'history.persistence="none"',
    "notify=[]",
)


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def user_config_ids(config_path: Path | None = None) -> dict[str, list[str]]:
    path = config_path or codex_home() / "config.toml"
    if not path.exists():
        return {"mcp_servers": [], "plugins": []}
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    return {
        "mcp_servers": sorted(config.get("mcp_servers", {})),
        "plugins": sorted(config.get("plugins", {})),
    }


def isolation_overrides(
    config_path: Path | None = None, enable_features: tuple[str, ...] = ()
) -> tuple[list[str], list[str]]:
    """Return (`-c` argument list, identifiers that could not be addressed by a dotted override)."""
    values = list(BASE_OVERRIDES)
    values += [f"features.{name}={'true' if name in enable_features else 'false'}" for name in DISABLED_FEATURES]
    unaddressable: list[str] = []
    ids = user_config_ids(config_path)
    for server in ids["mcp_servers"]:
        if "." in server or '"' in server:
            unaddressable.append(f"mcp_servers:{server}")
        else:
            values.append(f"mcp_servers.{server}.enabled=false")
    for plugin in ids["plugins"]:
        if "." in plugin or '"' in plugin:
            unaddressable.append(f"plugins:{plugin}")
        else:
            values.append(f"plugins.{plugin}.enabled=false")
    args: list[str] = []
    for value in values:
        args += ["-c", value]
    return args, unaddressable
