"""Interrupted shell check: detached Chrome exists before the first snapshot."""
import importlib.util
from pathlib import Path
import signal
import pytest


def load_install():
    spec = importlib.util.spec_from_file_location("install_check", Path(__file__).resolve().parents[1] / "scripts/p9/install_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("foreign,survive", [(True, False), (False, False), (False, True)])
def test_interrupted_unrecorded_chrome_and_descendants_are_killed_and_reaudited(tmp_path, monkeypatch, foreign, survive):
    mod = load_install()
    audit = mod.Audit.__new__(mod.Audit)
    audit.work = tmp_path
    audit.tmp = tmp_path / "tmp"
    audit.groups, audit.procs, audit.audit_set, audit.rows, audit.findings = {}, {}, {}, {}, []
    audit.port = 8951
    table = [dict(pid=100, ppid=1, pgid=100, comm="/Applications/Chrome", cmd=f"/Applications/Chrome --user-data-dir={audit.tmp}/playwright_chromiumdev_profile-rrb"),
             dict(pid=101, ppid=100, pgid=101, cmd="Chrome helper"),
             dict(pid=102, ppid=101, pgid=102, cmd="Chrome grandchild")]
    if foreign:
        table.append(dict(pid=200, ppid=1, pgid=200, cmd=f"tail {tmp_path}/log"))
    monkeypatch.setattr(mod, "ps_table", lambda: list(table))
    monkeypatch.setattr(mod, "own_exclusions", lambda _: set())
    monkeypatch.setattr(mod, "command_of", lambda pid: next((r["cmd"] for r in table if r["pid"] == pid), None))
    monkeypatch.setattr(mod, "comm_of", lambda pid: next((r.get("comm") for r in table if r["pid"] == pid), None))
    monkeypatch.setattr(mod, "port_listeners", lambda _: [])
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    sent = []

    def kill(pid, sig):
        sent.append((pid, sig))
        if not survive or pid != 102:
            table[:] = [r for r in table if r["pid"] != pid]

    monkeypatch.setattr(mod.os, "kill", kill)
    audit.final_audit()
    assert {pid for pid, _ in sent} == {100, 101, 102}
    assert (102, signal.SIGKILL) in sent if survive else all(sig == signal.SIGTERM for _, sig in sent)
    evidence = audit.rows["cleanup"]["evidence"][0]
    assert evidence["reaudited"] is True
    assert evidence["alive_before_cleanup"]
    assert all(str(200 if foreign else 102) in entry for entry in evidence["alive"])
    assert audit.rows["cleanup"]["result"] == ("fail" if foreign or survive else "pass")


def test_pid_command_change_is_never_signalled(tmp_path, monkeypatch):
    mod = load_install()
    audit = mod.Audit.__new__(mod.Audit)
    audit.tmp, audit.groups = tmp_path, {100: "original"}
    monkeypatch.setattr(mod, "ps_table", lambda: [dict(pid=100, ppid=1, pgid=100, cmd="replacement")])
    monkeypatch.setattr(mod, "own_exclusions", lambda _: set())
    monkeypatch.setattr(mod, "command_of", lambda _: "replacement")
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    monkeypatch.setattr(mod.os, "kill", lambda *args: (_ for _ in ()).throw(AssertionError(args)))
    audit.kill_recorded({100: "original"})


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


def _audit(mod, tmp_path, monkeypatch, table, groups):
    audit = mod.Audit.__new__(mod.Audit)
    audit.work = tmp_path
    audit.tmp = tmp_path / "tmp"
    audit.groups, audit.procs, audit.audit_set, audit.rows, audit.findings = dict(groups), {}, {}, {}, []
    audit.port = 8951
    monkeypatch.setattr(mod, "ps_table", lambda: list(table))
    monkeypatch.setattr(mod, "own_exclusions", lambda _: set())
    monkeypatch.setattr(mod, "command_of", lambda pid: next((r["cmd"] for r in table if r["pid"] == pid), None))
    monkeypatch.setattr(mod, "comm_of", lambda pid: next((r.get("comm") for r in table if r["pid"] == pid), None))
    monkeypatch.setattr(mod, "port_listeners", lambda _: [])
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    monkeypatch.setattr(mod.os, "kill", lambda *args: (_ for _ in ()).throw(AssertionError(args)))
    monkeypatch.setattr(mod.os, "killpg", lambda *args: (_ for _ in ()).throw(AssertionError(args)))
    return audit


def test_a_script_with_chrome_in_its_name_and_the_profile_argument_is_not_signalled(tmp_path, monkeypatch):
    mod = load_install()
    profile = tmp_path / "tmp" / "playwright_chromiumdev_profile-rrb"
    table = [dict(pid=310, ppid=1, pgid=310, comm="/usr/bin/python3", cmd=f"/usr/bin/python3 /opt/chrome_profile_backup.py --user-data-dir={profile}")]
    _audit(mod, tmp_path, monkeypatch, table, {}).final_audit()
    for cmd in (f"/usr/bin/python3 /opt/chrome --user-data-dir={profile}", f"/usr/bin/python3 Chrome.app/Contents/MacOS/Chrome --user-data-dir={profile}",
                f"/Applications/Backup.app/Contents/MacOS/Chrome --user-data-dir={profile}-abc",
                f"/Applications/Google Chrome.app/Contents/Backup.app/Contents/MacOS/Chrome --user-data-dir={profile}-abc",
                f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={profile}-rrb/../../../foreign-profile",
                f"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir={profile}-rrb /../../../foreign-profile"):
        table = [dict(pid=311, ppid=1, pgid=311, comm=cmd.split(" --")[0].split(" ")[0] if "python3" in cmd else cmd.split(" --")[0], cmd=cmd)]
        _audit(mod, tmp_path, monkeypatch, table, {}).final_audit()


def test_real_chrome_command_lines_are_recognised(monkeypatch):
    mod = load_install()
    profile = "/tmp/playwright_chromiumdev_profile"
    for exe in ("/Users/x/Library/Caches/ms-playwright/chromium-1/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        monkeypatch.setattr(mod, "comm_of", lambda pid, exe=exe: exe)
        assert mod.is_chrome_with_profile(dict(pid=1, cmd=f"{exe} --user-data-dir={profile}-abc --headless"), profile), exe
    monkeypatch.setattr(mod, "comm_of", lambda pid: "/usr/bin/python3")
    assert not mod.is_chrome_with_profile(dict(pid=1, cmd=f"/Applications/Google Chrome --app=https://x.invalid/ --user-data-dir={profile}-abc"), profile)


def test_a_reused_group_id_with_another_command_is_not_signalled_by_the_final_audit(tmp_path, monkeypatch):
    mod = load_install()
    table = [dict(pid=400, ppid=1, pgid=400, cmd="/bin/sleep 60")]
    audit = _audit(mod, tmp_path, monkeypatch, table, {400: "original-uv-command"})
    audit.final_audit()


def test_a_foreign_chrome_with_another_profile_and_the_harness_profile_in_a_url_is_not_signalled(tmp_path, monkeypatch):
    mod = load_install()
    profile = tmp_path / "tmp" / "playwright_chromiumdev_profile-rrb"
    table = [dict(pid=320, ppid=1, pgid=320, comm="/Applications/Google Chrome", cmd=f"/Applications/Google Chrome --user-data-dir=/foreign-profile https://example.invalid/?q=--user-data-dir={profile}")]
    _audit(mod, tmp_path, monkeypatch, table, {}).final_audit()


def test_a_group_whose_leader_is_gone_and_a_foreign_process_naming_the_work_directory_are_not_signalled(tmp_path, monkeypatch):
    mod = load_install()
    table = [dict(pid=401, ppid=1, pgid=400, cmd=f"foreign {tmp_path}/x"), dict(pid=402, ppid=1, pgid=402, cmd=f"tail {tmp_path}/log")]
    audit = _audit(mod, tmp_path, monkeypatch, table, {400: "original-uv-command"})
    audit.audit_set.update({401: table[0]["cmd"], 402: table[1]["cmd"]})
    audit.final_audit()
    assert audit.rows["cleanup"]["result"] == "fail"


def test_a_live_leader_started_by_the_harness_is_owned_after_its_command_changed_by_exec(tmp_path, monkeypatch):
    mod = load_install()
    table = [dict(pid=500, ppid=1, pgid=500, cmd="/real/node server.js"), dict(pid=501, ppid=500, pgid=501, cmd="child")]
    audit = _audit(mod, tmp_path, monkeypatch, table, {500: f"{tmp_path}/bin/node server.js"})
    audit.procs = {500: type("P", (), {"poll": lambda self: None})()}
    assert audit.owned_pids(table) == {500, 501}
