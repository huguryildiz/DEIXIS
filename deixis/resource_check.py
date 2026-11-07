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
import os
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


def runtime_main(args: list[str]) -> int:
    """`deixis-backend --check-runtime FOLDER [--https URL] [--probe EXE]` (P10 W3): the native code the packaged backend
    loads in its own process, run after the frozen entry's DLL search reset, for the Windows release smoke. In FOLDER a
    synthetic PDF is written, opened and one page rendered (MuPDF); a throwaway Credential Locker entry is written, read
    and deleted (keyring); an https request goes to URL through the system trust store (truststore, ssl); and EXE, a
    program outside the package, is started the way an external tool is (`child_env`) and its output reported. One JSON
    line; exit 0 when every check asked for passed."""
    import secrets
    import subprocess

    folder = Path(args[0])
    options = dict(zip(args[1::2], args[2::2]))
    checks: dict[str, dict] = {}

    def check(name: str, run) -> None:
        try:
            checks[name] = {"ok": True, **run()}
        except Exception as exc:  # noqa: BLE001 - every failure is reported, none stops the check
            checks[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}

    def pdf() -> dict:
        import pymupdf

        path = folder / "runtime-check.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "SYNTHETIC runtime check")
        doc.save(path)
        with pymupdf.open(path) as opened:
            pixmap = opened[0].get_pixmap(dpi=72)
            text = opened[0].get_text()
        return {"pixels": pixmap.width * pixmap.height, "text": "SYNTHETIC" in text}

    def credentials() -> dict:
        import keyring

        service, value = f"DEIXIS-runtime-check-{secrets.token_hex(6)}", secrets.token_hex(8)
        keyring.set_password(service, "check", value)
        try:
            read = keyring.get_password(service, "check")
        finally:
            keyring.delete_password(service, "check")
        if read != value or keyring.get_password(service, "check") is not None:
            raise RuntimeError("the stored value did not come back, or was not deleted")
        return {"backend": type(keyring.get_keyring()).__name__}

    def https() -> dict:
        import httpx

        from deixis.system_trust import use_system_certificates

        use_system_certificates()
        response = httpx.get(options["--https"], timeout=30, follow_redirects=False)
        return {"status": response.status_code}

    def probe() -> dict:
        from deixis.tools.child_env import child_env

        done = subprocess.run([options["--probe"]], env=child_env(), capture_output=True, text=True, timeout=60,
                              creationflags=0x08000000 if sys.platform == "win32" else 0)
        if done.returncode != 0:
            raise RuntimeError(f"exit {done.returncode}: {(done.stdout + done.stderr).strip()[-300:]}")
        return {"said": done.stdout.strip()[-300:]}

    def library_paths() -> dict:
        """Linux (P10 L3): the LD_LIBRARY_PATH an outside program gets on each route DEIXIS starts one by. None may name
        a folder of the package: `child_env` (tools, probes), a copy of this process's environment (what the Claude SDK
        passes its CLI) and the session launcher (the model CLIs), which is itself a frozen child of this binary."""
        from deixis.tools import child_record
        from deixis.tools.child_env import child_env

        package = Path(sys.executable).resolve().parent
        program = [options["--library-probe"]]

        def seen(argv: list[str], env: dict) -> str:
            done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
            lines = done.stdout.strip().splitlines()
            if done.returncode != 0 or not lines:
                raise RuntimeError(f"{argv[0]}: exit {done.returncode}: {(done.stdout + done.stderr).strip()[-300:]}")
            return lines[-1].partition("=")[2]

        routes = {"child_env": seen(program, child_env()), "environ_copy": seen(program, dict(os.environ)),
                  "launcher": seen(child_record.launcher_argv(program, "cli"), child_env())}
        leaked = {route: value for route, value in routes.items()
                  if any(Path(d).resolve().is_relative_to(package) for d in value.split(":") if d)}
        if leaked:
            raise RuntimeError(f"the package's library folder reached an outside program: {leaked}")
        return {"routes": routes, "own": os.environ.get("LD_LIBRARY_PATH", "")}

    check("pdf_render", pdf)
    check("credential_locker", credentials)
    if "--https" in options:
        check("https", https)
    if "--probe" in options:
        check("dll_probe", probe)
    if "--library-probe" in options:
        check("library_paths", library_paths)
    ok = all(c["ok"] for c in checks.values())
    print(json.dumps({"event": "runtime", "ok": ok, "checks": checks}))
    return 0 if ok else 1
