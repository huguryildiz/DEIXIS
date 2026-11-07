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
import json
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
    """Relative path -> sha256 of the content; a symlink is `link:<target>`, not its target's content."""
    return {p.relative_to(folder).as_posix(): f"link:{os.readlink(p)}" if p.is_symlink() else sha256(p)
            for p in sorted(folder.rglob("*")) if p.is_file()}


def compare(expected: dict[str, str], found: dict[str, str], root: Path) -> tuple[list[str], list[str]]:
    """(differences, dereferenced links). The bundler copies a symlink as a regular file; that copy counts as equal
    only when its content is its target's, and it is named in the build output."""
    differ, dereferenced = [], []
    for name in sorted(set(expected) | set(found)):
        want, got = expected.get(name), found.get(name)
        if want == got:
            continue
        if want and got and want.startswith("link:") and not got.startswith("link:"):
            target = (Path(name).parent / want[5:]).as_posix()
            if expected.get(target) == got:
                dereferenced.append(name)
                continue
        differ.append(name)
    return differ, dereferenced


def is_elf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) == b"\x7fELF"


def elf_kind(path: Path) -> bytes:
    """Class, byte order, OS ABI, type and machine of an ELF file: what a RPATH rewrite never changes."""
    with path.open("rb") as handle:
        head = handle.read(20)
    return head[4:6] + head[7:8] + head[16:20]


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

    deb_dereferenced: list[str] = []
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
        differ, deb_dereferenced = compare(expected, files(inside), inside)
        if differ:
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
            changed, app_dereferenced = [], []
        else:
            found = files(inside)
            if set(found) != set(expected):
                problems.append(f"the AppImage's sidecar has other files than the build: "
                                f"missing {sorted(set(expected) - set(found))[:10]}, added {sorted(set(found) - set(expected))[:10]}")
            differ, app_dereferenced = compare(expected, found, inside)
            # linuxdeploy may rewrite an ELF file's RPATH; any other changed file is a problem.
            changed = [n for n in differ if n in found and n in expected and (inside / n).is_file() and is_elf(inside / n)
                       and is_elf(built / n) and elf_kind(built / n) == elf_kind(inside / n)]
            if other := [n for n in differ if n in found and n not in changed]:
                problems.append(f"the AppImage's sidecar changed files that are not ELF: {other[:20]}")
            (UNPACKED / "appimage-changes.json").write_text(json.dumps(
                {n: {"build": expected[n], "appimage": found[n]} for n in changed}, indent=1))
            if not os.access(inside / "deixis-backend", os.X_OK):
                problems.append("the AppImage's deixis-backend is not executable")
            shutil.copytree(inside, UNPACKED / "appimage-sidecar", symlinks=True)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    for package in (deb, appimage):
        print(f"{package.name}: {package.stat().st_size / 1e6:.1f} MB, sha256 {sha256(package)}")
    print(f"sidecar {built}: {folder_bytes(built) / 1e6:.1f} MB, {len(expected)} files; equal inside the .deb; inside the "
          f"AppImage {len(changed)} ELF files rewritten by linuxdeploy (all in {UNPACKED / 'appimage-changes.json'}); "
          f"symlinks copied as files by the bundler: .deb {deb_dereferenced}, AppImage {app_dereferenced}; "
          f"deixis-backend sha256 {sha256(built / 'deixis-backend')}; build {time.monotonic() - started:.0f} s")
    print(f"appimage-sidecar {UNPACKED / 'appimage-sidecar'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
