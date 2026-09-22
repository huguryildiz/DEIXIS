"""`python -m deixis serve` options: what the command line changes and what it must leave alone.

No model, no provider and no server are involved; `serve` is replaced by a recorder, so these show the launcher's
handling of the settings it was given.
"""

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
    assert settings.search_workflow == "sw"
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
    assert settings.search_workflow == "sw"
