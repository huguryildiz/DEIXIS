"""Where the app's own read-only files are: contracts, the method package and the built web app (pre-P10 A1)."""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """A packaged (PyInstaller) build rather than a run from the repository."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """DEIXIS_REPO_ROOT, else the unpacked bundle of a frozen build (`sys._MEIPASS`), else the repository root.
    `package_manifest.DATAS` lists what a build puts here."""
    if env := os.environ.get("DEIXIS_REPO_ROOT"):
        return Path(env)
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


RESOURCE_ROOT = resource_root()
CONTRACTS_DIR = RESOURCE_ROOT / "deixis" / "contracts" / "research"
SKILL_DIR = RESOURCE_ROOT / "deixis" / "methods" / "deixis-research"
REPO_ROOT = RESOURCE_ROOT  # the name the repository's own scripts use; the same folder outside a frozen build
