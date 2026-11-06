"""Build DEIXIS.app and its DMG for macOS arm64 (P10 M2), end to end.

    uv run --group packaging python packaging/build_mac.py [--skip-sidecar] [--skip-web]

Steps: the backend sidecar (packaging/sidecar/build.py: web build, PyInstaller onedir, ad-hoc signature on every Mach-O
file, `--check-resources`), then the Tauri shell (`npm ci` and `tauri build --bundles app` in desktop/, which copies the
sidecar into `Contents/Resources/sidecar/deixis-backend/` and signs the app ad hoc, `signingIdentity: "-"`).

Tauri copies resources with their symlinks resolved; the onedir build has six (the Python framework's layout and two
MuPDF library names), and a resolved framework binary no longer verifies. So the copy's symlinks are put back as the
build has them, the app is sealed again (`codesign --force --sign -` on the bundle) and the DMG is made here with
`hdiutil` from that app (the app and an Applications link). Checks: `codesign --verify --deep --strict` on the app,
a valid signature on every Mach-O file inside it, and the copied sidecar equal to the build (files and symlinks).
Prints the .app and .dmg sizes and paths. Rust comes from Homebrew's rustup (`/opt/homebrew/opt/rustup/bin`). uv is not
bundled.
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
APP = BUNDLE / "macos" / "DEIXIS.app"
RUSTUP = "/opt/homebrew/opt/rustup/bin"

sys.path.insert(0, str(SIDECAR))
from build import folder_bytes, is_macho, run  # noqa: E402


def files(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and not p.is_symlink()}


def links(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): os.readlink(p) for p in sorted(folder.rglob("*")) if p.is_symlink()}


def restore_links(built: Path, inside: Path) -> int:
    """Put the build's symlinks back in the app's copy of the sidecar, where Tauri copied their targets."""
    for name, target in links(built).items():
        path = inside / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        path.symlink_to(target)
    return len(links(built))


def make_dmg(app: Path, dmg: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="deixis-dmg-") as folder:
        staging = Path(folder) / "DEIXIS"
        staging.mkdir()
        run(["ditto", str(app), str(staging / app.name)])
        (staging / "Applications").symlink_to("/Applications")
        dmg.parent.mkdir(parents=True, exist_ok=True)
        dmg.unlink(missing_ok=True)
        run(["hdiutil", "create", "-volname", "DEIXIS", "-srcfolder", str(staging), "-fs", "HFS+", "-format", "UDZO",
             "-ov", str(dmg)])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-sidecar", action="store_true", help="use the existing packaging/sidecar/dist build")
    parser.add_argument("--skip-web", action="store_true", help="passed to the sidecar build")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        print(f"This build is for macOS arm64; this Python is {sys.platform} {platform.machine()}.", file=sys.stderr)
        return 2
    started = time.monotonic()
    if not args.skip_sidecar:
        run([sys.executable, str(SIDECAR / "build.py"), *(["--skip-web"] if args.skip_web else [])])
    built = SIDECAR / "dist" / "deixis-backend"
    if not (built / "deixis-backend").is_file():
        print(f"No sidecar build in {built}; run without --skip-sidecar.", file=sys.stderr)
        return 2
    env = os.environ | {"PATH": f"{RUSTUP}:{os.environ.get('PATH', '')}"}
    run(["npm", "ci"], cwd=DESKTOP, env=env)
    run(["npx", "tauri", "build", "--bundles", "app"], cwd=DESKTOP, env=env)
    inside = APP / "Contents" / "Resources" / "sidecar" / "deixis-backend"
    restored = restore_links(built, inside)
    run(["codesign", "--force", "--sign", "-", str(APP)])
    run(["codesign", "--verify", "--deep", "--strict", str(APP)])
    unsigned = [p for p in (APP / "Contents").rglob("*") if p.is_file() and not p.is_symlink() and is_macho(p)
                and subprocess.run(["codesign", "--verify", str(p)], capture_output=True).returncode != 0]
    if unsigned:
        print("Mach-O files without a valid signature:\n" + "\n".join(map(str, unsigned[:20])), file=sys.stderr)
        return 1
    if files(inside) != files(built) or links(inside) != links(built):
        print(f"The sidecar inside the app differs from {built}.", file=sys.stderr)
        return 1
    version = json.loads((DESKTOP / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
    dmg = BUNDLE / "dmg" / f"DEIXIS_{version}_aarch64.dmg"
    make_dmg(APP, dmg)
    print(f"restored {restored} symlinks; app {APP}: {folder_bytes(APP) / 1e6:.1f} MB; dmg {dmg}: "
          f"{dmg.stat().st_size / 1e6:.1f} MB; build {time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
