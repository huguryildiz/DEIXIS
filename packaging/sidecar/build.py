"""Build the DEIXIS backend sidecar for macOS arm64 (P10 M1) or Windows x64 (P10 W3).

    uv run --group packaging python packaging/sidecar/build.py [--skip-web]

Steps: `npm run build` in web (the bundle serves web/dist), the OCR language files pinned in
packaging/tesseract-versions.json (downloaded once into build/tessdata/, the build stops on a size or sha256 mismatch;
P10 M3), the build identity (sha256 of every package file, read by PRISMA-S exports), PyInstaller with deixis-backend.spec into packaging/sidecar/dist/deixis-backend/, on macOS an ad-hoc
signature (`codesign --force --sign -`) on every Mach-O file in it, and last `deixis-backend --check-resources` run
from the output. Prints the folder size and the build time. Windows builds are unsigned.
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
import sysconfig
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DIST = HERE / "dist"
WORK = HERE / "build"
OUTPUT = DIST / "deixis-backend"
TESSDATA = WORK / "tessdata"
TESSDATA_PINS = REPO / "packaging" / "tesseract-versions.json"
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


def _matches(path: Path, pin: dict) -> bool:
    return path.is_file() and path.stat().st_size == pin["bytes"] and hashlib.sha256(path.read_bytes()).hexdigest() == pin["sha256"]


def fetch_tessdata(folder: Path = TESSDATA, pins_file: Path = TESSDATA_PINS, download=urllib.request.urlopen) -> Path:
    """The pinned OCR language files in `folder`, each downloaded only when missing or different, plus PINS.json (the
    pins, read by `--check-resources` in the package). Raises SystemExit(1) on a size or sha256 mismatch, the bad file
    removed."""
    pins = json.loads(pins_file.read_text(encoding="utf-8"))["files"]
    folder.mkdir(parents=True, exist_ok=True)
    for name, pin in pins.items():
        path = folder / name
        if _matches(path, pin):
            continue
        if not pin["url"].startswith("https://"):
            raise SystemExit(f"{name}: the pinned URL is not https")
        print(f"+ download {pin['url']}", flush=True)
        with download(pin["url"], timeout=60) as response:
            path.write_bytes(response.read(pin["bytes"] + 1))
        if not _matches(path, pin):
            path.unlink(missing_ok=True)
            print(f"{name}: size or sha256 differs from {pins_file.name}; the build stops.", file=sys.stderr)
            raise SystemExit(1)
    (folder / "PINS.json").write_text(json.dumps({n: p["sha256"] for n, p in pins.items()}, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8")
    return folder


def folder_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and not p.is_symlink())


def stale_sources(built: Path, repo: Path = REPO) -> list[str]:
    """The package's Python files that have changed since this sidecar was built, newest first in no order.

    `--skip-sidecar` reuses `dist/deixis-backend` as it stands, and nothing else compares it with the working tree, so
    a build made after an edit ships the old Python without a word. That cost a day once: the packaged app kept a query
    that was already fixed in the repo, and the app looked frozen for half a minute at every start. The sidecar carries
    the sha256 of every file it was built from (`package_manifest.write_build_identity`), so this is a dict compare.
    """
    sys.path.insert(0, str(repo))
    from deixis.runtime import package_manifest

    found = next(built.rglob(package_manifest.BUILD_IDENTITY), None)
    if found is None:
        return [f"<no {package_manifest.BUILD_IDENTITY} in the sidecar>"]
    try:
        built_files = json.loads(found.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError):
        return [f"<{found} could not be read>"]
    now = {path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
           for path in sorted((repo / "deixis").rglob("*.py")) if "__pycache__" not in path.parts}
    return sorted(set(built_files) ^ set(now) | {name for name in built_files.keys() & now.keys()
                                                 if built_files[name] != now[name]})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-web", action="store_true", help="use the existing web/dist")
    args = parser.parse_args()
    windows = sysconfig.get_platform() == "win-amd64"  # this interpreter's own build (an ARM64 host emulates x64)
    linux = sys.platform.startswith("linux")  # x86_64 is shipped (P10 L3); aarch64 builds for local checks only
    if not windows and not linux and (sys.platform != "darwin" or platform.machine() != "arm64"):
        print(f"This build is for macOS arm64, Windows x64 or Linux; this Python is {sys.platform} {platform.machine()}.",
              file=sys.stderr)
        return 2
    started = time.monotonic()
    if not args.skip_web:
        run([shutil.which("npm") or "npm", "run", "build"], cwd=REPO / "web")  # npm.cmd on Windows
    if not (REPO / "web" / "dist" / "index.html").is_file():
        print("web/dist/index.html is missing; run `npm run build` in web.", file=sys.stderr)
        return 2
    tessdata = fetch_tessdata()
    sys.path.insert(0, str(REPO))
    from deixis.runtime import package_manifest

    with tempfile.TemporaryDirectory(prefix="deixis-identity-") as folder:
        identity = package_manifest.write_build_identity(REPO, Path(folder))
        shutil.rmtree(OUTPUT, ignore_errors=True)
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
             "--distpath", str(DIST), "--workpath", str(WORK), str(HERE / "deixis-backend.spec")],
            env=os.environ | {"DEIXIS_BUILD_IDENTITY": str(identity), "DEIXIS_TESSDATA_DIR": str(tessdata)})
    if windows:
        signed = 0
        env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA",
                                                             "APPDATA", "PATHEXT", "COMSPEC")}
        env["PATH"] = str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32")
    else:
        signed = 0 if linux else sign_all(OUTPUT)
        if not linux:
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
