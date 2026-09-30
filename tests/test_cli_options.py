"""`python -m deixis serve` options: what the command line changes and what it must leave alone.

No model, no provider and no server are involved; `serve` is replaced by a recorder, so these show the launcher's
handling of the settings it was given.
"""

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
    monkeypatch.setenv("DEIXIS_QUERY_STRATEGY", "compact_openalex_v1")
    monkeypatch.setenv("DEIXIS_MODEL_CONCURRENCY", "3")
    settings = settings_of(["serve", "--port", "8799", "--no-browser"], monkeypatch, tmp_path)
    assert settings.port == 8799
    assert not hasattr(settings, "search_workflow")
    assert settings.protocol_approval == "as_proposed"
    assert settings.fulltext_fetch == "off"
    assert settings.fulltext_adjudication == "off"
    assert settings.query_strategy == "compact_openalex_v1"
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
