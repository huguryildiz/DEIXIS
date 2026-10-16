"""The Codex subprocess environment carries no provider or application secrets."""

from pathlib import Path

from deixis.models.adapter import codex_environment


def test_codex_environment_keeps_runtime_variables_and_drops_secrets(monkeypatch):
    monkeypatch.setattr("deixis.models.adapter.find_tool", lambda name: None)
    monkeypatch.setattr("deixis.tools.tool_paths.find_tool", lambda name: None)  # no real codex or node folder joins PATH
    source = {
        "PATH": "/usr/bin", "HOME": "/Users/someone", "LC_ALL": "C", "HTTPS_PROXY": "http://proxy.local:3128",
        "OPENALEX_API_KEY": "secret", "DEEPSEEK_API_KEY": "secret", "DEIXIS_CONTACT_EMAIL": "someone@example.org",
        "CODEX_HOME": "/somewhere/else",
    }
    env = codex_environment(Path("/tmp/deixis-codex-home"), source)
    assert env == {"PATH": "/usr/bin", "HOME": "/Users/someone", "LC_ALL": "C", "HTTPS_PROXY": "http://proxy.local:3128",
                   "CODEX_HOME": "/tmp/deixis-codex-home"}


def test_codex_app_server_starts_with_analytics_and_feedback_off(tmp_path):
    from deixis.models.codex_isolation import isolation_overrides

    args, _ = isolation_overrides(config_path=tmp_path / "config.toml")
    pairs = [args[i + 1] for i in range(0, len(args), 2) if args[i] == "-c"]
    assert "analytics.enabled=false" in pairs and "feedback.enabled=false" in pairs
