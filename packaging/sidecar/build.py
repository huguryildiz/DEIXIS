"""Build the DEIXIS backend sidecar for macOS arm64 (P10 M1) or Windows x64 (P10 W3).

    uv run --group packaging python packaging/sidecar/build.py [--skip-web]

Steps: `npm run build` in web (the bundle serves web/dist), the build identity (sha256 of every package file, read by
PRISMA-S exports), PyInstaller with deixis-backend.spec into packaging/sidecar/dist/deixis-backend/, on macOS an ad-hoc
signature (`codesign --force --sign -`) on every Mach-O file in it, and last `deixis-backend --check-resources` run
from the output. Prints the folder size and the build time. Windows builds are unsigned.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DIST = HERE / "dist"
WORK = HERE / "build"
OUTPUT = DIST / "deixis-backend"
MACHO_MAGIC = {bytes.fromhex(m) for m in ("feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca")}


def run(argv: list[str], cwd: Path = REPO, env: dict | None = None) -> None:
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=cwd, env=env, check=True)


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACHO_MAGIC
    except OSError:
        return False


def sign_all(folder: Path) -> int:
    """Ad-hoc sign every Mach-O file, the deepest first and the main executable last (Apple Silicon runs no unsigned code)."""
    files = [p for p in folder.rglob("*") if p.is_file() and not p.is_symlink() and is_macho(p)]
    files.sort(key=lambda p: (p == folder / "deixis-backend", -len(p.parts)))
    for path in files:
        subprocess.run(["codesign", "--force", "--sign", "-", str(path)], check=True, capture_output=True)
    return len(files)


def folder_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and not p.is_symlink())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-web", action="store_true", help="use the existing web/dist")
    args = parser.parse_args()
    windows = sysconfig.get_platform() == "win-amd64"  # this interpreter's own build (an ARM64 host emulates x64)
    if not windows and (sys.platform != "darwin" or platform.machine() != "arm64"):
        print(f"This build is for macOS arm64 or Windows x64; this Python is {sys.platform} {platform.machine()}.",
              file=sys.stderr)
        return 2
    started = time.monotonic()
    if not args.skip_web:
        run([shutil.which("npm") or "npm", "run", "build"], cwd=REPO / "web")  # npm.cmd on Windows
    if not (REPO / "web" / "dist" / "index.html").is_file():
        print("web/dist/index.html is missing; run `npm run build` in web.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(REPO))
    from deixis import package_manifest

    with tempfile.TemporaryDirectory(prefix="deixis-identity-") as folder:
        identity = package_manifest.write_build_identity(REPO, Path(folder))
        shutil.rmtree(OUTPUT, ignore_errors=True)
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
             "--distpath", str(DIST), "--workpath", str(WORK), str(HERE / "deixis-backend.spec")],
            env=os.environ | {"DEIXIS_BUILD_IDENTITY": str(identity)})
    if windows:
        signed = 0
        env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA",
                                                             "APPDATA", "PATHEXT", "COMSPEC")}
        env["PATH"] = str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32")
    else:
        signed = sign_all(OUTPUT)
        run(["codesign", "--verify", str(OUTPUT / "deixis-backend")])
        env = {k: v for k, v in os.environ.items() if k in ("HOME", "TMPDIR", "LANG", "LC_ALL", "USER")}
        env["PATH"] = "/usr/bin:/bin"
    run([str(OUTPUT / ("deixis-backend.exe" if windows else "deixis-backend")), "--check-resources"],
        cwd=Path(tempfile.gettempdir()), env=env)
    print(f"signed {signed} Mach-O files; {OUTPUT}: {folder_bytes(OUTPUT) / 1e6:.1f} MB; "
          f"build {time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
