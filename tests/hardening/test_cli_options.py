"""`python -m deixis serve` options: what the command line changes and what it must leave alone.

No model, no provider and no server are involved; `serve` is replaced by a recorder, so these show the launcher's
handling of the settings it was given. The data-directory tests at the end run the real `serve` up to the point where
it would build the app, which they forbid.
"""

import os

import pytest

from deixis import __main__ as cli


def settings_of(argv, monkeypatch, tmp_path):
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path))
    seen = {}

    def record(settings, open_browser, dev_hosts):
        seen["settings"] = settings
        return 0

    monkeypatch.setattr(cli, "serve", record)
    assert cli.main(argv) == 0
    return seen["settings"]


def test_a_port_on_the_command_line_keeps_every_other_setting(monkeypatch, tmp_path):
    """`--port` moves the server; it is not a reason to run a different workflow (slice 13 smoke run)."""
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    monkeypatch.setenv("DEIXIS_PROTOCOL_APPROVAL", "as_proposed")
    monkeypatch.setenv("DEIXIS_FULLTEXT_FETCH", "off")
    monkeypatch.setenv("DEIXIS_FULLTEXT_ADJUDICATION", "off")
    monkeypatch.setenv("DEIXIS_MODEL_CONCURRENCY", "3")
    settings = settings_of(["serve", "--port", "8799", "--no-browser"], monkeypatch, tmp_path)
    assert settings.port == 8799
    assert not hasattr(settings, "search_workflow")
    assert settings.protocol_approval == "as_proposed"
    assert settings.fulltext_fetch == "off"
    assert settings.fulltext_adjudication == "off"
    assert settings.model_concurrency == 3
    assert settings.data_dir == tmp_path


def test_without_a_port_the_environment_decides(monkeypatch, tmp_path):
    monkeypatch.setenv("DEIXIS_PORT", "8801")
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "sw")
    settings = settings_of(["serve", "--no-browser"], monkeypatch, tmp_path)
    assert settings.port == 8801
    assert not hasattr(settings, "search_workflow")


@pytest.mark.parametrize("command", ["serve", "backup", "restore"])
def test_obsolete_workflow_env_warns_once_and_does_not_block_commands(monkeypatch, tmp_path, command):
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "legacy")
    monkeypatch.setenv("DEIXIS_DATA_DIR", str(tmp_path / "data"))
    called = []
    monkeypatch.setattr(cli, "serve", lambda *args: called.append("serve") or 0)
    monkeypatch.setattr(cli.backup, "create_backup", lambda *args: called.append("backup") or tmp_path / "backup")
    monkeypatch.setattr(cli.backup, "restore_backup", lambda *args: called.append("restore") or {"researches": 0, "files": 0})
    args = ["serve", "--no-browser"] if command == "serve" else [command, str(tmp_path / "backup")]
    with pytest.warns(UserWarning, match="DEIXIS_SEARCH_WORKFLOW is ignored") as caught:
        assert cli.main(args) == 0
    assert len(caught) == 1 and called == [command]


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


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only directory")
def test_serve_names_a_missing_data_directory_under_a_read_only_parent(monkeypatch, tmp_path, capsys):
    parent = tmp_path / "parent"
    parent.mkdir()
    parent.chmod(0o555)
    try:
        assert run_serve(monkeypatch, tmp_path, parent / "sub") == 2
        assert listing(parent) == []
    finally:
        parent.chmod(0o755)
    err = capsys.readouterr().err
    assert str(parent / "sub") in err and "not writable" in err and str(parent) in err


@pytest.mark.skipif(os.geteuid() == 0, reason="root can search any directory")
def test_a_parent_that_cannot_be_searched_is_reported_not_raised(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    parent.chmod(0)
    try:
        assert cli.data_dir_problem(parent / "sub") == "is not writable"
    finally:
        parent.chmod(0o755)


def test_a_data_directory_under_a_regular_file_is_not_a_folder(tmp_path):
    (tmp_path / "file").write_text("x")
    before = listing(tmp_path)
    assert cli.data_dir_problem(tmp_path / "file" / "sub") == "is not a folder"
    assert cli.data_dir_problem(tmp_path / "file") == "is not a folder"
    assert listing(tmp_path) == before


def test_a_writable_or_not_yet_created_data_directory_has_no_problem(tmp_path):
    (tmp_path / "data").mkdir()
    before = listing(tmp_path)
    assert cli.data_dir_problem(tmp_path / "data") is None
    assert cli.data_dir_problem(tmp_path / "data" / "new" / "deeper") is None
    assert listing(tmp_path) == before
