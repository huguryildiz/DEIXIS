# PyInstaller spec of the DEIXIS backend sidecar (P10 M1, W3, L3): one folder (onedir), macOS arm64, Windows x64
# (deixis-backend.exe and _internal\) or Linux x86_64 (deixis-backend and _internal/).
# Built by packaging/sidecar/build.py, which first builds the web app and writes the build identity it passes in
# DEIXIS_BUILD_IDENTITY; run that script, not this file directly.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

from deixis import package_manifest

REPO = Path(SPECPATH).resolve().parents[1]
identity = Path(os.environ["DEIXIS_BUILD_IDENTITY"])

# Never shipped: the Claude CLI copy inside the SDK (192 MB; the person's own `claude` is used), and test and build tools.
DROPPED = ("claude_agent_sdk/_bundled", "claude_agent_sdk\\_bundled")
EXCLUDES = ["pytest", "_pytest", "testmon", "pytest_testmon", "xdist", "execnet", "pluggy", "iniconfig",
            "tkinter", "_tkinter", "PyInstaller", "IPython", "pip", "setuptools", "wheel", "tests"]

a = Analysis(
    [str(REPO / "deixis" / "frozen_entry.py")],
    pathex=[str(REPO)],
    binaries=[],
    datas=package_manifest.datas(REPO, identity) + copy_metadata("deixis"),
    hiddenimports=list(package_manifest.HIDDEN_IMPORTS),
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
a.datas = [entry for entry in a.datas if not any(part in entry[0] or part in entry[1] for part in DROPPED)]
a.binaries = [entry for entry in a.binaries if not any(part in entry[0] or part in entry[1] for part in DROPPED)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="deixis-backend",
    console=True,
    target_arch="arm64" if sys.platform == "darwin" else None,
    codesign_identity=None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="deixis-backend", upx=False)
