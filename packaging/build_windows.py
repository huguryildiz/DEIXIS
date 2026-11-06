"""Build the DEIXIS Windows x64 installer (P10 W3), end to end.

    uv run --group packaging python packaging/build_windows.py [--skip-sidecar] [--skip-web]

Steps: the backend sidecar (packaging/sidecar/build.py: web build, PyInstaller onedir `deixis-backend.exe` + `_internal\\`,
`--check-resources`), then the Tauri shell (`npm ci` and `tauri build` in desktop/, whose Windows config makes the NSIS
installer and copies the sidecar to `sidecar\\deixis-backend\\`). Checks: the installer exists, and the sidecar inside it,
unpacked with 7-Zip (which reads NSIS installers), equals the build file for file. Prints the installer's path, size and
SHA-256 and the sidecar's SHA-256. Unsigned: SmartScreen asks on first run.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "packaging" / "sidecar"
DESKTOP = REPO / "desktop"
NSIS = DESKTOP / "src-tauri" / "target" / "release" / "bundle" / "nsis"

sys.path.insert(0, str(SIDECAR))
from build import folder_bytes, run  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def files(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def seven_zip() -> str | None:
    found = shutil.which("7z")
    default = Path(r"C:\Program Files\7-Zip\7z.exe")
    return found or (str(default) if default.is_file() else None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-sidecar", action="store_true", help="use the existing packaging/sidecar/dist build")
    parser.add_argument("--skip-web", action="store_true", help="passed to the sidecar build")
    args = parser.parse_args()
    if sysconfig.get_platform() != "win-amd64":
        print(f"This build is for Windows x64; this Python is {sysconfig.get_platform()}.", file=sys.stderr)
        return 2
    started = time.monotonic()
    if not args.skip_sidecar:
        run([sys.executable, str(SIDECAR / "build.py"), *(["--skip-web"] if args.skip_web else [])])
    built = SIDECAR / "dist" / "deixis-backend"
    if not (built / "deixis-backend.exe").is_file():
        print(f"No sidecar build in {built}; run without --skip-sidecar.", file=sys.stderr)
        return 2
    npm, npx = shutil.which("npm"), shutil.which("npx")  # npm.cmd, npx.cmd
    if not npm or not npx:
        print("npm is not on PATH.", file=sys.stderr)
        return 2
    run([npm, "ci"], cwd=DESKTOP)
    run([npx, "tauri", "build", "--ci"], cwd=DESKTOP)
    installers = sorted(NSIS.glob("*-setup.exe"), key=lambda p: p.stat().st_mtime)
    if not installers:
        print(f"No installer in {NSIS}.", file=sys.stderr)
        return 1
    installer = installers[-1]
    if (tool := seven_zip()) is None:
        print("7-Zip is needed to check the sidecar inside the installer.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="deixis-installer-") as folder:
        subprocess.run([tool, "x", "-y", f"-o{folder}", str(installer)], check=True, capture_output=True)
        inside = next((p.parent for p in Path(folder).rglob("deixis-backend.exe")
                       if p.parent.name == "deixis-backend" and p.parent.parent.name == "sidecar"), None)
        if inside is None:
            print("The installer holds no sidecar\\deixis-backend\\deixis-backend.exe.", file=sys.stderr)
            return 1
        expected, found = files(built), files(inside)
        if found != expected:
            differ = sorted(n for n in set(expected) | set(found) if expected.get(n) != found.get(n))
            print(f"The sidecar inside the installer differs from {built}: {differ[:20]}", file=sys.stderr)
            return 1
    print(f"installer {installer}: {installer.stat().st_size / 1e6:.1f} MB, sha256 {sha256(installer)}")
    print(f"sidecar {built}: {folder_bytes(built) / 1e6:.1f} MB, {len(expected)} files equal inside the installer, "
          f"deixis-backend.exe sha256 {sha256(built / 'deixis-backend.exe')}; build {time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
