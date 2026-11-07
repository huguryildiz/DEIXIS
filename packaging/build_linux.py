"""Build the DEIXIS Linux x64 packages (P10 L4), end to end: a `.deb` and an AppImage.

    uv run --group packaging python packaging/build_linux.py [--skip-sidecar] [--skip-web]

Steps: the backend sidecar (packaging/sidecar/build.py: web build, PyInstaller onedir `deixis-backend` + `_internal/`,
`--check-resources`), then the Tauri shell (`npm ci` and `tauri build` in desktop/, whose Linux config makes the `.deb`
and the AppImage and copies the sidecar to `usr/lib/DEIXIS/sidecar/deixis-backend/`). Checks:
- the `.deb`, unpacked with `dpkg-deb -x`: the sidecar equals the build file for file (content; Tauri copies symlinks
  resolved), `deixis-backend` and the shell are executable, and the package's Depends name WebKitGTK 4.1 and the
  indicator library (the tray loads it at run time and panics without it);
- the AppImage, unpacked with `--appimage-extract`: linuxdeploy rewrites the RPATH of ELF files under `usr/lib`, so its
  sidecar is not byte-compared; its files are hashed and the ones that differ from the build are named (none may be
  missing or added), and `--appimage-sidecar` prints the unpacked sidecar's folder for the second smoke run in CI.
Prints each package's path, size and SHA-256. Unsigned.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECAR = REPO / "packaging" / "sidecar"
DESKTOP = REPO / "desktop"
BUNDLE = DESKTOP / "src-tauri" / "target" / "release" / "bundle"
UNPACKED = REPO / "packaging" / "linux-unpacked"  # kept for the smoke run against the AppImage's own sidecar

sys.path.insert(0, str(SIDECAR))
from build import folder_bytes, run  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def files(folder: Path) -> dict[str, str]:
    """Relative path -> sha256 of the content (a symlink to a file counts as that file's content)."""
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def newest(pattern: str) -> Path | None:
    found = sorted(BUNDLE.glob(pattern), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def sidecar_in(root: Path) -> Path | None:
    return next((p.parent for p in root.rglob("deixis-backend") if p.is_file() and p.parent.name == "deixis-backend"
                 and p.parent.parent.name == "sidecar"), None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-sidecar", action="store_true", help="use the existing packaging/sidecar/dist build")
    parser.add_argument("--skip-web", action="store_true", help="passed to the sidecar build")
    args = parser.parse_args()
    if not sys.platform.startswith("linux") or platform.machine() not in ("x86_64", "AMD64"):
        print(f"This build is for Linux x86_64; this Python is {sys.platform} {platform.machine()}.", file=sys.stderr)
        return 2
    started = time.monotonic()
    if not args.skip_sidecar:
        run([sys.executable, str(SIDECAR / "build.py"), *(["--skip-web"] if args.skip_web else [])])
    built = SIDECAR / "dist" / "deixis-backend"
    if not (built / "deixis-backend").is_file():
        print(f"No sidecar build in {built}; run without --skip-sidecar.", file=sys.stderr)
        return 2
    run(["npm", "ci"], cwd=DESKTOP)
    run(["npx", "tauri", "build", "--ci"], cwd=DESKTOP)
    deb, appimage = newest("deb/*.deb"), newest("appimage/*.AppImage")
    if deb is None or appimage is None:
        print(f"Missing package in {BUNDLE}: deb {deb}, AppImage {appimage}.", file=sys.stderr)
        return 1
    expected = files(built)
    problems: list[str] = []
    shutil.rmtree(UNPACKED, ignore_errors=True)
    UNPACKED.mkdir(parents=True)

    deb_root = UNPACKED / "deb"
    subprocess.run(["dpkg-deb", "-x", str(deb), str(deb_root)], check=True)
    depends = subprocess.run(["dpkg-deb", "-f", str(deb), "Depends"], capture_output=True, text=True, check=True).stdout
    for needed in ("libwebkit2gtk-4.1-0", "libayatana-appindicator3-1"):
        if needed not in depends:
            problems.append(f".deb Depends lacks {needed}: {depends.strip()}")
    inside = sidecar_in(deb_root)
    if inside is None:
        problems.append("the .deb holds no sidecar/deixis-backend/deixis-backend")
    else:
        found = files(inside)
        if found != expected:
            differ = sorted(n for n in set(expected) | set(found) if expected.get(n) != found.get(n))
            problems.append(f"the .deb's sidecar differs from the build: {differ[:20]}")
        if not os.access(inside / "deixis-backend", os.X_OK):
            problems.append("the .deb's deixis-backend is not executable")
    shells = [p for p in (deb_root / "usr" / "bin").glob("*") if p.is_file()]
    if not shells or not all(os.access(p, os.X_OK) for p in shells):
        problems.append(f"the .deb's shell in usr/bin is missing or not executable: {shells}")

    with tempfile.TemporaryDirectory(prefix="deixis-appimage-") as folder:
        subprocess.run([str(appimage), "--appimage-extract"], cwd=folder, check=True, capture_output=True)
        squash = Path(folder) / "squashfs-root"
        inside = sidecar_in(squash)
        if inside is None:
            problems.append("the AppImage holds no sidecar/deixis-backend/deixis-backend")
            changed: list[str] = []
        else:
            found = files(inside)
            if set(found) != set(expected):
                problems.append(f"the AppImage's sidecar has other files than the build: "
                                f"missing {sorted(set(expected) - set(found))[:10]}, added {sorted(set(found) - set(expected))[:10]}")
            changed = sorted(n for n in expected if n in found and expected[n] != found[n])
            if not os.access(inside / "deixis-backend", os.X_OK):
                problems.append("the AppImage's deixis-backend is not executable")
            shutil.copytree(inside, UNPACKED / "appimage-sidecar", symlinks=True)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    for package in (deb, appimage):
        print(f"{package.name}: {package.stat().st_size / 1e6:.1f} MB, sha256 {sha256(package)}")
    print(f"sidecar {built}: {folder_bytes(built) / 1e6:.1f} MB, {len(expected)} files; equal inside the .deb; inside the "
          f"AppImage {len(changed)} rewritten by linuxdeploy ({', '.join(changed[:8])}{' ...' if len(changed) > 8 else ''}); "
          f"deixis-backend sha256 {sha256(built / 'deixis-backend')}; build {time.monotonic() - started:.0f} s")
    print(f"appimage-sidecar {UNPACKED / 'appimage-sidecar'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
