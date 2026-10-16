"""The environment of every child process DEIXIS starts that is not a model CLI (pre-P10 A5, E4).

An allowlist, not a copy of os.environ with a few names removed: the keys DEIXIS loads from the keychain live in its
environment (OPENAI_API_KEY, GITHUB_TOKEN, MATHPIX_CREDENTIALS, ...) and an installer or a PDF child must see none of
them. A child gets what the operating system needs to run a process, PATH, and only the names its caller adds. Proxy
settings go only to a child that uses the network. The model CLIs have their own lists (`codex_environment` and the like).

In a frozen (PyInstaller) build the bundle sets the library search path for its own libraries. A child that is part of
the bundle keeps it; an outside program (uv, npm, Homebrew, Tesseract) gets the value from before the bundle started,
or none, as PyInstaller's documentation asks, or it would load the bundle's libraries instead of its own.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from deixis.paths import is_frozen
from deixis.tools.tool_paths import child_path

OS_VARIABLES = frozenset({
    "HOME", "USER", "LOGNAME", "TMPDIR", "LANG",  # POSIX; LC_* is added by prefix
    "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC", "USERPROFILE", "LOCALAPPDATA", "APPDATA",  # Windows
})
OS_PREFIXES = ("LC_",)  # the locale settings
NETWORK_VARIABLES = frozenset({
    "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
})
# Python's system-certificate setting (system_trust.py) does not reach other programs; these do for uv and Node.
UV_TLS = {"UV_NATIVE_TLS": "1"}
NODE_TLS = {"NODE_USE_SYSTEM_CA": "1"}  # Node 22.19 / 24.6 and later; older Node ignores it
# DEIXIS's own switches that the app's Python children read (the memory guard, the repo root); none holds a secret.
BUNDLED_VARIABLES = frozenset({"DEIXIS_REPO_ROOT", "DEIXIS_CHILD_LIFETIME_SECONDS", "DEIXIS_CHILD_GUARD_DISABLED",
                               "DEIXIS_CHILD_GUARD_LOG"})
LIBRARY_PATHS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "LIBPATH")


def child_env(extra: Mapping[str, str] | None = None, *, keep: Iterable[str] = (), network: bool = False,
              bundled: bool = False, tool: str | None = None, source: Mapping[str, str] | None = None) -> dict[str, str]:
    """`extra` is set as given; `keep` names variables copied from `source` when present; `tool` is the found program,
    whose folder (and node's) goes on PATH; `bundled` marks a child that is part of the app (the PDF children)."""
    source = os.environ if source is None else source
    names = OS_VARIABLES | set(keep) | (NETWORK_VARIABLES if network else frozenset()) | (BUNDLED_VARIABLES if bundled else frozenset())
    env = {k: v for k, v in source.items() if k in names or k.startswith(OS_PREFIXES)}
    env["PATH"] = child_path(tool, source.get("PATH", ""))
    if not is_frozen():
        env.update({k: source[k] for k in LIBRARY_PATHS if k in source})  # the person's own setting, kept
    else:
        for name in LIBRARY_PATHS:
            if bundled:
                env.update({k: source[k] for k in (name, f"{name}_ORIG") if k in source})
            elif f"{name}_ORIG" in source:
                env[name] = source[f"{name}_ORIG"]
        if bundled:
            env.update({k: v for k, v in source.items() if k.startswith(("_PYI_", "_MEIPASS"))})
    env.update(extra or {})
    return env
