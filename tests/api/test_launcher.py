"""Launcher and command-line hardening: options, data folder checks, idle and forced shutdown, schema refusal at start,
tool lookup, Windows launch, process cleanup, notices file and the capacity script's guards.

Fake processes, servers and file systems; no real tool is started. Passing shows the guards hold on this machine's
simulations, not on every platform.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import pytest
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from scripts.licenses import build_notices as notices
from types import SimpleNamespace

from deixis import __main__ as cli
from deixis import __main__ as launcher
from deixis.config import Settings
from deixis.keys import account_signin
from deixis.keys.account_signin import build_launch
from deixis.models import claude
from deixis.storage import backup
from deixis.storage import db
from deixis.tools import tool_paths
from deixis.tools.tool_paths import command_for
from test_restore_matrix import entry
from test_restore_matrix import file_facts
from test_restore_matrix import folder_names
from test_restore_matrix import hand_backup
from test_restore_matrix import library_with_id_only_in_the_wal
from test_restore_matrix import write_manifest
from test_restore_matrix import fake_uvicorn  # noqa: F401  (fixtures used by name)


def settings_of(argv, monkeypatch, tmp_path):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path))
    seen = {}

    def record(settings, open_browser, dev_hosts, **options):
        seen["settings"] = settings
        return 0

    monkeypatch.setattr(cli, "serve", record)
    assert cli.main(argv) == 0
    return seen["settings"]


def test_a_port_on_the_command_line_keeps_every_other_setting(monkeypatch, tmp_path):
    """`--port` moves the server; it is not a reason to run a different workflow (slice 13 smoke run)."""
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    monkeypatch.setenv("DEIXIS_FULLTEXT_FETCH", "off")
    monkeypatch.setenv("DEIXIS_FULLTEXT_ADJUDICATION", "off")
    monkeypatch.setenv("DEIXIS_MODEL_CONCURRENCY", "3")
    settings = settings_of(["serve", "--port", "8799", "--no-browser"], monkeypatch, tmp_path)
    assert settings.port == 8799
    assert not hasattr(settings, "search_workflow")
    assert settings.fulltext_fetch == "off"
    assert settings.fulltext_adjudication == "off"
    assert settings.model_concurrency == 3
    assert settings.data_dir == tmp_path


def listing(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def run_serve(monkeypatch, tmp_path, data_dir):
    """`serve` with the port reported free (the default port is the owner's live service) and no app to build."""
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(data_dir))

    def refuse(*args, **kwargs):
        raise AssertionError("create_app must not run when the data directory is unusable")

    monkeypatch.setattr(cli, "port_available", lambda host, port: True)
    monkeypatch.setattr(cli, "create_app", refuse)
    return cli.main(["serve", "--no-browser"])


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only directory")
def test_serve_names_an_unwritable_data_directory_and_stops(monkeypatch, tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o555)
    try:
        before = listing(tmp_path)
        assert run_serve(monkeypatch, tmp_path, data) == 2
        assert listing(tmp_path) == before
    finally:
        data.chmod(0o755)
    err = capsys.readouterr().err
    assert str(data) in err and "not writable" in err and "Traceback" not in err


def watch(server, last, busy):
    cancel = threading.Event()
    thread = threading.Thread(target=launcher.watch_idle, args=(server, 0.2, last, busy, cancel, 0.05), daemon=True)
    thread.start()
    return thread, cancel


@pytest.mark.parametrize("recent, busy", [(True, False), (False, True)])
def test_keeps_running_with_a_recent_request_or_a_working_run(recent, busy):
    server = SimpleNamespace(should_exit=False)
    thread, cancel = watch(server, (lambda: time.monotonic()) if recent else (lambda: time.monotonic() - 10), lambda: busy)
    time.sleep(0.5)
    assert not server.should_exit and thread.is_alive()
    cancel.set()
    thread.join(2)


def make_library(path, run_status, fetch_status=None):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE runs (status TEXT)")
    conn.execute("CREATE TABLE fast_path_background_fetches (status TEXT)")
    conn.execute("INSERT INTO runs VALUES (?)", (run_status,))
    if fetch_status:
        conn.execute("INSERT INTO fast_path_background_fetches VALUES (?)", (fetch_status,))
    conn.commit()
    conn.close()


def start(server, seconds, cancel):
    exits = []
    thread = threading.Thread(target=launcher.watch_shutdown, args=(server, seconds, exits.append, cancel), daemon=True)
    thread.start()
    return thread, exits


def test_exits_once_with_the_forced_code_after_the_grace_period(capsys):
    server, cancel = SimpleNamespace(should_exit=False), threading.Event()
    thread, exits = start(server, 0.3, cancel)
    server.should_exit = True
    thread.join(5)
    assert exits == [launcher.FORCED_EXIT_CODE]
    assert "did not finish shutting down" in capsys.readouterr().err


@pytest.mark.parametrize("operation", [db.check_schema_known])
def test_symlink_uses_the_real_wal_for_schema_refusal(tmp_path, operation):
    path = library_with_id_only_in_the_wal(tmp_path / "source")
    link = tmp_path / "alias" / "library.sqlite"
    link.parent.mkdir()
    link.symlink_to(path)
    before = file_facts(path.parent), folder_names(path.parent)
    with pytest.raises(db.UnknownSchemaError, match="9999"):
        operation(link)
    assert (file_facts(path.parent), folder_names(path.parent)) == before


@pytest.mark.parametrize("damage", ["integrity"])
def test_staged_database_is_verified_and_removed_on_failure(tmp_path, monkeypatch, damage):
    source = hand_backup(tmp_path, papers=0, payloads=0)
    if damage == "integrity":
        (source / "library.sqlite").write_bytes(b"SYNTHETIC damaged SQLite database" * 100)
        write_manifest(source, [entry(source, "library.sqlite")])
    target = Settings(data_dir=tmp_path / "restored")
    real_copy = backup.shutil.copyfile
    replaced = []
    real_replace = backup.os.replace
    real_connect = sqlite3.connect
    closed = []

    class IntegrityFailure(sqlite3.Connection):
        def close(self):
            super().close()
            closed.append(True)

    def connect(path, *args, **kwargs):
        if damage == "integrity" and "mode=ro" in str(path):
            return real_connect(":memory:")  # the read-only preflight passes, so the staged copy's own check is what refuses
        if damage == "integrity" and str(path).endswith(".restoring"):
            kwargs["factory"] = IntegrityFailure
        return real_connect(path, *args, **kwargs)

    def copy(src, dest, *args, **kwargs):
        result = real_copy(src, dest, *args, **kwargs)
        if str(dest).endswith(".restoring"):
            if damage == "text":
                with sqlite3.connect(dest) as conn:
                    assert conn.execute("UPDATE researches SET title = 'SYNTHETIC changed title'").rowcount == 1
                    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return result

    def replace(src, dest):
        replaced.append((src, dest))
        return real_replace(src, dest)

    monkeypatch.setattr(backup.shutil, "copyfile", copy)
    monkeypatch.setattr(backup.os, "replace", replace)
    monkeypatch.setattr(backup.sqlite3, "connect", connect)
    with pytest.raises((backup.BackupError, sqlite3.DatabaseError)) as caught:
        backup.restore_backup(source, target)
    if damage == "text":
        assert isinstance(caught.value, backup.BackupError)
        assert str(caught.value) == "restored database does not match the manifest"
    else:
        assert closed == [True]
    assert not target.db_path.exists()
    assert not target.db_path.with_name("library.sqlite.restoring").exists()
    assert replaced == []


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the fake tools and shells are shell scripts")


def tool(folder: Path, name: str = "codex") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\necho fake\n")
    path.chmod(0o755)
    return path


def shell(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture
def short_path(monkeypatch):
    """What a Finder-started app sees: no tool folders on PATH, no shell asked, no known folders (the autouse fixture)."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(tool_paths, "_shell_path", None)
    monkeypatch.setattr(tool_paths, "SHELL_TIMEOUT", 20.0)  # a busy test machine starts a script slowly; the timeout tests set their own
    monkeypatch.delenv("SHELL", raising=False)


@posix_only
def test_the_login_shell_gets_a_minimal_environment_and_no_key_or_proxy(tmp_path, monkeypatch, short_path):
    seen = tmp_path / "env"
    login = shell(tmp_path / "zsh", f"env > {seen}\nprintf '__DEIXIS_PATH__%s__END__' \"$PATH\"\n")
    for name, value in {"OPENAI_API_KEY": "sk-shell-secret", "GITHUB_TOKEN": "ghp_shell-secret", "MATHPIX_CREDENTIALS": "m-secret",
                        "HTTPS_PROXY": "http://user:pw@proxy:3128", "no_proxy": "x", "FOO": "bar"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SHELL", str(login))
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/process/path")
    tool_paths.login_shell_path()
    given = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert not {"OPENAI_API_KEY", "GITHUB_TOKEN", "MATHPIX_CREDENTIALS", "HTTPS_PROXY", "no_proxy", "FOO"} & set(given)
    assert "secret" not in seen.read_text() and "proxy" not in seen.read_text().lower()
    assert given["PATH"].startswith("/usr/bin:/bin:/process/path") and given["LC_ALL"] == "C" and given["SHELL"] == str(login)
    assert {"HOME"} <= set(given)


def test_no_module_looks_for_a_tool_with_shutil_which_any_more():
    root = Path(tool_paths.__file__).parents[1]
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if p.name != "tool_paths.py" and "shutil.which" in p.read_text()]
    assert offenders == []


HOSTILE = "a&b %x% ^c (d) !e"  # cmd.exe metacharacters and a space in one folder name


SHIM = '''@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0

IF EXIST "%dp0%\\node.exe" (
  SET "_prog=%dp0%\\node.exe"
) ELSE (
  SET "_prog=node"
  SET PATHEXT=%PATHEXT:;.JS;=;%
)

endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\{entry}" %*
'''


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(tool_paths.sys, "platform", "win32")  # the same module object everywhere
    monkeypatch.setattr(tool_paths.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(tool_paths, "find_tool", lambda name: None)  # no node on the search path unless a test adds one


def touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def npm_install(folder: Path, name: str, entry: str, node: bool = True) -> Path:
    """What `npm install -g` leaves on Windows: <name>.cmd, the script it names, and node.exe when npm brought it."""
    touch(folder / f"{name}.cmd", SHIM.format(entry=entry))
    touch(folder / Path(*entry.split("\\")))
    if node:
        touch(folder / "node.exe")
    return folder / f"{name}.cmd"


def no_batch(argv: list[str]) -> bool:
    return not any(Path(part).suffix.lower() in (".cmd", ".bat") or Path(part).name.lower() == "cmd.exe" for part in argv)


@pytest.mark.parametrize("name,entry", [("codex", "node_modules\\@openai\\codex\\bin\\codex.js")])
def test_a_path_with_batch_metacharacters_never_reaches_a_batch_file(windows, tmp_path, name, entry):
    launcher = npm_install(tmp_path / HOSTILE, name, entry)
    argv = command_for(name, str(launcher)).argv
    assert argv and no_batch(argv)
    assert argv[0].endswith("node.exe") and HOSTILE in argv[1]


def script_of(argv: list[str]) -> str:
    assert argv[-2] == "-EncodedCommand"
    return base64.b64decode(argv[-1]).decode("utf-16-le")


def test_windows_sign_in_hands_powershell_an_encoded_script_and_no_cmd_line():
    home = Path(f"C:/Users/{HOSTILE}/it's/codex-home")
    argv = build_launch("win32", f"C:\\{HOSTILE}\\node.exe", [f"C:\\{HOSTILE}\\o'brien\\codex.js", "login"], home, which=lambda n: None)
    assert argv[0] == "powershell.exe" and "-NoExit" in argv and no_batch(argv)
    script = script_of(argv)
    assert f"$env:CODEX_HOME = 'C:/Users/{HOSTILE}/it''s/codex-home'" in script
    assert script.endswith(f"& 'C:\\{HOSTILE}\\node.exe' 'C:\\{HOSTILE}\\o''brien\\codex.js' 'login'")
    plain = script_of(build_launch("win32", "C:\\bin\\claude.exe", ["auth", "login"], None, which=lambda n: "C:\\ps\\powershell.exe"))
    assert "CODEX_HOME" not in plain and plain.endswith("& 'C:\\bin\\claude.exe' 'auth' 'login'")
    # The argv words are plain: nothing in them for any shell to read.
    assert all(not set("&|<>^%\"") & set(part) for part in argv)


def load_install():
    spec = importlib.util.spec_from_file_location("install_check", Path(__file__).resolve().parents[2] / "scripts/release_checks/install_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_foreign_process_naming_the_profile_path_is_not_signalled(tmp_path, monkeypatch):
    mod = load_install()
    audit = mod.Audit.__new__(mod.Audit)
    audit.work = tmp_path
    audit.tmp = tmp_path / "tmp"
    audit.groups, audit.procs, audit.audit_set, audit.rows, audit.findings = {}, {}, {}, {}, []
    audit.port = 8951
    table = [dict(pid=300, ppid=1, pgid=300, comm="/usr/bin/tail", cmd=f"tail -f {audit.tmp}/playwright_chromiumdev_profile-rrb/Default/chrome_debug.log")]
    monkeypatch.setattr(mod, "ps_table", lambda: list(table))
    monkeypatch.setattr(mod, "own_exclusions", lambda _: set())
    monkeypatch.setattr(mod, "command_of", lambda pid: next((r["cmd"] for r in table if r["pid"] == pid), None))
    monkeypatch.setattr(mod, "comm_of", lambda pid: next((r.get("comm") for r in table if r["pid"] == pid), None))
    monkeypatch.setattr(mod, "port_listeners", lambda _: [])
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    monkeypatch.setattr(mod.os, "kill", lambda *args: (_ for _ in ()).throw(AssertionError(args)))
    audit.final_audit()
    assert audit.rows["cleanup"]["result"] == "fail"


REPO = Path(__file__).resolve().parents[2]


def _build(web: Path):
    entries = notices.python_entries([]) + notices.npm_entries(web)
    problems = notices.resolve(entries)
    return notices.render(entries, "NATIVE"), problems


def test_the_committed_notices_file_covers_every_production_dependency():
    text = (REPO / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
    assert "MuPDF" in text and "Tesseract" in text and "Tauri" in text and "marker-pdf" not in text  # Marker removed (D113)
    for name, version in notices.python_requirements():
        assert f"python {name} {version}" in text
    lock = json.loads((REPO / "web/package-lock.json").read_text(encoding="utf-8"))
    for key, info in lock["packages"].items():
        if key and not info.get("dev"):
            assert f"npm    {key.rsplit('node_modules/', 1)[-1]} {info['version']}" in text


_spec = importlib.util.spec_from_file_location("capacity", REPO / "scripts" / "release_checks" / "capacity.py")


capacity = importlib.util.module_from_spec(_spec)


sys.modules["capacity"] = capacity


_spec.loader.exec_module(capacity)


# (class, [(metric, points, limit, strict)]) per row id.


def results(**by_point):
    return {str(point): metrics for point, metrics in by_point.items()}


def test_only_ports_8900_to_8920_are_allowed():
    assert capacity.guard_port(8900) == 8900 and capacity.guard_port(8920) == 8920
    for port in (8765, 8860, 8858, 8864, 8899, 8921, 0, 5178):
        with pytest.raises(capacity.GuardError):
            capacity.guard_port(port)


def test_the_child_environment_is_an_allowlist(tmp_path):
    env = capacity.child_env(tmp_path / "home", tmp_path / "data")
    assert set(env) == {"PATH", "HOME", "PYTHONPATH", "PYTHON_KEYRING_BACKEND", "DEIXIS_DATA_DIR"}
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
    assert not any(shutil.which(name, path=env["PATH"]) for name in ("codex", "claude", "gemini"))


@pytest.fixture(scope="module")
def library():
    root = Path(tempfile.mkdtemp(prefix="h5-"))
    info = capacity.generate_point(root, 100)
    yield root, info
    shutil.rmtree(root, ignore_errors=True)


