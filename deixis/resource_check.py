"""`deixis --check-resources` (P10 M1): read-only check that a build holds every file and module the app needs.

Resolved from inside the running process, so a packaged build checks the paths its own code reads (`sys._MEIPASS`),
not a folder listing: the contracts, the method package (with its integrity check), the library schema, the built web
app and every `package_manifest.DATAS` entry, and every module in `package_manifest.HIDDEN_IMPORTS` is imported. Writes
nothing; exit 0 when all are present, else 1 with one line per missing item. The JSON line also names the sha256 of
the build identity file this process holds, so a smoke run can tie the running binary to the code it was built from.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def problems() -> list[str]:
    from deixis import package_manifest, paths
    from deixis.domain import skill
    from deixis.storage import db

    missing: list[str] = []
    root = paths.RESOURCE_ROOT
    if not any(paths.CONTRACTS_DIR.glob("*.schema.json")):
        missing.append(f"contracts: no *.schema.json in {paths.CONTRACTS_DIR}")
    if not paths.SKILL_DIR.is_dir():
        missing.append(f"method package: {paths.SKILL_DIR} missing")
    elif issues := skill.integrity_issues():
        missing.append(f"method package integrity: {issues}")
    if not db.SCHEMA.is_file():
        missing.append(f"library schema: {db.SCHEMA} missing")
    web_dist = root / "web" / "dist"  # config.Settings.web_dist, without loading the person's settings
    if not (web_dist / "index.html").is_file():
        missing.append(f"web app: {web_dist / 'index.html'} missing")
    for pattern, dest in package_manifest.DATAS:
        # `datas()` puts a matched file at dest/<name> and a folder's contents at dest itself
        name, folder = Path(pattern).name, root / dest
        if "*" in name:
            present = any(folder.glob(name))
        else:
            present = (folder / name).is_file() or (Path(dest).name == name and folder.is_dir() and any(folder.iterdir()))
        if not present:
            missing.append(f"manifest: {pattern} not found under {folder}")
    if getattr(sys, "frozen", False):
        identity = root / "deixis" / package_manifest.BUILD_IDENTITY
        if not identity.is_file():
            missing.append(f"build identity: {identity} missing")
    try:
        version("deixis")
    except PackageNotFoundError:
        missing.append("package metadata: importlib.metadata.version('deixis') not found")
    for module in package_manifest.HIDDEN_IMPORTS:
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - every failure is reported, none stops the check
            missing.append(f"module {module}: {type(exc).__name__}: {exc}")
    return missing


def identity_sha256() -> str | None:
    from deixis import package_manifest, paths

    identity = paths.RESOURCE_ROOT / "deixis" / package_manifest.BUILD_IDENTITY
    return hashlib.sha256(identity.read_bytes()).hexdigest() if identity.is_file() else None


def main() -> int:
    found = problems()
    for line in found:
        print(line, file=sys.stderr)
    print(json.dumps({"event": "resources", "ok": not found, "missing": len(found), "build_identity_sha256": identity_sha256()}))
    return 1 if found else 0
