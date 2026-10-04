"""The Codex subprocess environment carries no provider or application secrets."""

from pathlib import Path

from deixis.models.adapter import codex_environment


def test_codex_environment_keeps_runtime_variables_and_drops_secrets():
    source = {
        "PATH": "/usr/bin", "HOME": "/Users/someone", "LC_ALL": "C", "HTTPS_PROXY": "http://proxy.local:3128",
        "OPENALEX_API_KEY": "secret", "DEEPSEEK_API_KEY": "secret", "DEIXIS_CONTACT_EMAIL": "someone@example.org",
        "CODEX_HOME": "/somewhere/else",
    }
    env = codex_environment(Path("/tmp/deixis-codex-home"), source)
    assert env == {"PATH": "/usr/bin", "HOME": "/Users/someone", "LC_ALL": "C", "HTTPS_PROXY": "http://proxy.local:3128",
                   "CODEX_HOME": "/tmp/deixis-codex-home"}
