"""Settings → General → Research and Settings → Data: stored preferences, backup, Library export and cache clearing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from deixis import config
from deixis.storage import data_location
from deixis.api.app import create_app
from deixis.config import Settings
from fakes import FakeAdapter


@pytest.fixture
def client(tmp_path, monkeypatch):
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr(config, "platform_data_dir", lambda: folder)
    monkeypatch.delenv("DEIXIS_DATA_DIR", raising=False)
    monkeypatch.setattr(data_location, "backup_dir", lambda: tmp_path / "backups")
    app = create_app(Settings(data_dir=folder, port=8765, model_concurrency=3, fulltext_fetch="off"), adapters={"fake": FakeAdapter()},
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as c:
        c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
        c.app_state = app.state
        c.folder = folder
        yield c


def test_unset_preferences_show_the_values_deixis_started_with(client):
    view = client.get("/api/settings/preferences").json()
    assert view["default_effort"] == "standard" and view["fulltext_fetch"] == "off"
    assert view["arxiv_source"] == "off" and view["model_concurrency"] == 3 and view["model_concurrency_max"] == 16


def test_a_stored_preference_comes_before_the_start_value_and_applies_at_once(client):
    view = client.put("/api/settings/preferences", json={"default_effort": "detailed", "fulltext_fetch": "auto",
                                                         "arxiv_source": "auto", "model_concurrency": 9}).json()
    assert (view["default_effort"], view["fulltext_fetch"], view["arxiv_source"], view["model_concurrency"]) == ("detailed", "auto", "auto", 9)
    state = client.app_state
    assert state.settings.effective_fulltext_fetch() == "auto"
    assert state.equations.arxiv_mode == "auto" and state.limiter.limit == 9
    # A partial change leaves the others as stored.
    assert client.put("/api/settings/preferences", json={"model_concurrency": 2}).json()["default_effort"] == "detailed"
    assert state.limiter.limit == 2


@pytest.mark.parametrize("bad", [{"model_concurrency": 0}, {"model_concurrency": 17}, {"default_effort": "huge"},
                                 {"fulltext_fetch": "on"}, {"unknown": 1}])
def test_an_invalid_preference_is_refused_and_nothing_is_stored(client, bad):
    assert client.put("/api/settings/preferences", json=bad).status_code == 422
    assert client.get("/api/settings/preferences").json()["model_concurrency"] == 3


def test_a_backup_is_written_and_named_in_the_view(client, tmp_path):
    view = client.post("/api/settings/data/backup").json()
    last = view["last_backup"]
    assert last["path"].startswith(str(tmp_path / "backups")) and (tmp_path / "backups").exists()
    assert (data_location.Path(last["path"]) / "manifest.json").exists()


def test_clearing_the_cache_removes_only_the_download_cache(client):
    cache = client.folder / "tools" / "uv-cache"
    cache.mkdir(parents=True)
    (cache / "wheel.bin").write_bytes(b"x" * 100)
    (client.folder / "tools" / "embedding").mkdir()
    assert client.get("/api/settings/data-location").json()["cache_bytes"] == 100
    view = client.post("/api/settings/data/clear-cache").json()
    assert view["cache_bytes"] == 0 and not cache.exists() and (client.folder / "tools" / "embedding").exists()


def test_exporting_an_empty_library_says_it_has_no_works(client):
    response = client.post("/api/library/bibliography", json={"format": "bibtex", "every_work": True})
    assert response.status_code == 422 and "no works" in response.json()["detail"]
