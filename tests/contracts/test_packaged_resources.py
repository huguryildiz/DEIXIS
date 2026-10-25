"""A packaged build finds its own files and leaves its install folder alone (pre-P10 A1, A2).

The frozen app is simulated: `sys.frozen` and `sys._MEIPASS` are set by hand, and the bundle is a temp folder holding
the package as `.pyc` files only plus the files `package_manifest.datas()` lists. Passing shows the manifest is
complete for start-up and that no `.py` source is read; it is not a PyInstaller build, which P10d checks.
"""

from __future__ import annotations

import compileall
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from deixis import config, package_manifest, paths
from deixis.keys import credentials
from deixis.domain import skill

REPO = Path(__file__).resolve().parents[2]
METADATA = Path(importlib.metadata.distribution("deixis")._path)  # the dev install's dist-info


def bundle(tmp_path: Path) -> Path:
    """The package compiled to sourceless `.pyc` files, the manifest's data files and the `deixis` dist-info that
    P10d's `copy_metadata("deixis")` adds, and nothing else."""
    root = tmp_path / "bundle"
    shutil.copytree(REPO / "deixis", root / "deixis",
                    ignore=lambda folder, names: [n for n in names if not (n.endswith(".py") or Path(folder, n).is_dir())
                                                  or n == "__pycache__"])
    assert compileall.compile_dir(root / "deixis", legacy=True, quiet=1)
    for source in (root / "deixis").rglob("*.py"):
        source.unlink()
    pairs = package_manifest.datas(REPO)
    if not any(dest.startswith("web/dist") for _, dest in pairs):  # the web app is not built in this checkout
        pairs.append((str(tmp_path / "index.html"), "web/dist"))
        (tmp_path / "index.html").write_text("<p>SYNTHETIC web build</p>")
    for source, dest in pairs:
        (root / dest).mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, root / dest)
    shutil.copytree(METADATA, root / METADATA.name)
    return root


def dependencies(tmp_path: Path) -> Path:
    """The dev environment's installed packages without its own `deixis` dist-info and `.pth` files (the editable
    install), so the child can only find DEIXIS and its metadata in the bundle."""
    folder = tmp_path / "site"
    folder.mkdir()
    for entry in Path(sysconfig.get_paths()["purelib"]).iterdir():
        if entry.resolve() != METADATA.resolve() and entry.suffix != ".pth":
            (folder / entry.name).symlink_to(entry)
    return folder


# Only what the OS and Python need; never a key or token from the shell that runs the tests.
CHILD_ENV = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "WINDIR",
             "USERPROFILE", "LOCALAPPDATA")


def run_frozen(root: Path, tmp_path: Path, body: str) -> dict:
    """Run `body` in an isolated Python (`-I -S`) that sees only the bundle and the dependencies, as a frozen app; it
    prints one JSON line."""
    env = {k: os.environ[k] for k in CHILD_ENV if k in os.environ}
    env |= {"DEIXIS_DATA_DIR": str(tmp_path / "data"), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
    script = (f"import sys\nsys.path[:0] = [{str(root)!r}, {str(dependencies(tmp_path))!r}]\n"
              f"sys.frozen = True\nsys._MEIPASS = {str(root)!r}\n" + body)
    done = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script], cwd=tmp_path, env=env, capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_resource_root_is_the_env_override_then_the_frozen_bundle_then_the_repository(monkeypatch, tmp_path):
    monkeypatch.delenv("DEIXIS_REPO_ROOT", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.resource_root() == REPO and not paths.is_frozen()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert paths.resource_root() == tmp_path / "bundle" and paths.is_frozen()
    monkeypatch.setenv("DEIXIS_REPO_ROOT", str(tmp_path / "chosen"))
    assert paths.resource_root() == tmp_path / "chosen"


def test_an_app_holding_only_the_manifest_files_starts_and_passes_the_integrity_check(tmp_path):
    root = bundle(tmp_path)
    (root / ".env").write_text("OPENALEX_API_KEY=SYNTHETIC-dotenv-key\n")  # never read by a frozen app (A2)
    seen = run_frozen(root, tmp_path, """
import importlib.metadata, json, os
from fastapi.testclient import TestClient
import deixis
from deixis.api.app import create_app
from deixis.config import load_settings
from deixis.domain import skill
from deixis.paths import RESOURCE_ROOT
app = create_app(load_settings(), start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
with TestClient(app) as client:
    health = client.get("/api/health").json()
    page = client.get("/").text
print(json.dumps({"package": deixis.__file__, "root": str(RESOURCE_ROOT), "issues": skill.integrity_issues(),
                  "health": health, "page": page, "key_set": "OPENALEX_API_KEY" in os.environ,
                  "metadata": str(importlib.metadata.distribution("deixis")._path),
                  "version": importlib.metadata.version("deixis")}))
""")
    assert seen["package"].startswith(str(root)) and seen["package"].endswith(".pyc") and seen["root"] == str(root)
    assert seen["issues"] == [] and seen["health"]["status"] == "ok"
    assert seen["health"]["skill_package_hash"] == skill.package_hash(REPO / "deixis" / "methods" / "deixis-research")
    assert "SYNTHETIC web build" in seen["page"] or "<div id=\"root\">" in seen["page"]
    assert seen["metadata"].startswith(str(root)) and seen["version"] == importlib.metadata.version("deixis")
    assert seen["key_set"] is False and (root / ".env").read_text() == "OPENALEX_API_KEY=SYNTHETIC-dotenv-key\n"
    assert not list(root.rglob("*.env.*"))


def test_the_manifest_lists_every_data_file_next_to_the_code_and_the_build_record():
    listed = {Path(source).resolve() for source, _ in package_manifest.datas(REPO)}
    package = REPO / "deixis"
    # Finder's .DS_Store files are not package data; git ignores them, but they sit on disk in a checkout.
    data_files = {p.resolve() for p in package.rglob("*")
                  if p.is_file() and p.suffix not in (".py", ".pyc") and p.name != ".DS_Store"}
    assert data_files <= listed
    assert all((REPO / "deixis/contracts/research" / name).resolve() in listed for name in os.listdir(REPO / "deixis/contracts/research"))
    assert (REPO / "deixis/methods/deixis-research/references/report.md").resolve() in listed
    assert package_manifest.datas(REPO, Path("/b/build_identity.json"))[-1] == ("/b/build_identity.json", "deixis")


# ---- .env (A2) --------------------------------------------------------------------------------------------------------


@pytest.fixture
def dotenv(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "RESOURCE_ROOT", tmp_path)
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENALEX_API_KEY", "unset")
    monkeypatch.delenv("OPENALEX_API_KEY")  # restored to absent afterwards, whatever load_settings sets
    path = tmp_path / ".env"
    path.write_text("# SYNTHETIC\nOPENALEX_API_KEY=openalex-dotenv-key\n")
    return path


def test_a_frozen_app_neither_reads_nor_writes_dotenv(dotenv, monkeypatch, memory_keychain):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    reads = []
    monkeypatch.setattr(config, "load_dotenv", lambda path: reads.append(path) or set())
    before = (dotenv.read_bytes(), dotenv.stat().st_mtime_ns)
    config.load_settings()
    assert reads == [] and credentials.dotenv_path is None and "OPENALEX_API_KEY" not in os.environ
    credentials.save("OPENALEX_API_KEY", "openalex-settings-key")
    assert memory_keychain.get_password("DEIXIS", "OPENALEX_API_KEY") == "openalex-settings-key"
    credentials.delete("OPENALEX_API_KEY")
    # Even with a path marked, the writer refuses in a frozen app.
    monkeypatch.setattr(credentials, "dotenv_path", dotenv)
    with pytest.raises(RuntimeError):
        credentials._rewrite_dotenv("OPENALEX_API_KEY", None)
    assert (dotenv.read_bytes(), dotenv.stat().st_mtime_ns) == before
    assert sorted(p.name for p in dotenv.parent.iterdir() if p.name.startswith(".env")) == [".env"]


def test_a_run_from_the_repository_still_reads_dotenv_and_moves_its_keys(dotenv, monkeypatch, memory_keychain):
    monkeypatch.delattr(sys, "frozen", raising=False)
    config.load_settings()
    assert credentials.dotenv_path == dotenv and os.environ["OPENALEX_API_KEY"] == "openalex-dotenv-key"
    assert memory_keychain.get_password("DEIXIS", "OPENALEX_API_KEY") == "openalex-dotenv-key"
    assert dotenv.read_text() == "# SYNTHETIC\n"  # moved into the keychain (D19), as before
