"""The keychain queue and the key stores without a keychain (E5, A6).

The keychains here are fakes in memory (a gate that never opens, one that refuses, none at all). They show how the app
handles a keychain that does not answer or does not exist; they say nothing about how a real macOS, Windows or Secret
Service keychain behaves when locked or asked for a password.
"""

import json
import os
import stat
import threading
import time

import httpx
import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import PasswordDeleteError, PasswordSetError

from deixis import credentials
from deixis.api.app import create_app
from deixis.config import Settings
from fakes import FakeAdapter

KEY = "OPENALEX_API_KEY"
V1, V2 = "openalex-source-good-v1", "openalex-source-good-v2"


class GateKeyring(KeyringBackend):
    """Memory keychain whose calls wait on `gate` when it is closed: the permission prompt or locked store that never answers."""

    priority = 1

    def __init__(self):
        super().__init__()
        self.items = {}
        self.gate = threading.Event()
        self.gate.set()
        self.close_for = set()  # which calls wait: 'get', 'set', 'delete'
        self.entered = threading.Event()

    def _wait(self, call):
        if call in self.close_for:
            self.entered.set()
            self.gate.wait(30)

    def get_password(self, service, username):
        self._wait("get")
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self._wait("set")
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        self._wait("delete")
        if self.items.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


class RefusingKeyring(KeyringBackend):
    priority = 1

    def get_password(self, service, username):
        raise PasswordSetError("locked")

    def set_password(self, service, username, password):
        raise PasswordSetError("locked")

    def delete_password(self, service, username):
        raise PasswordDeleteError("locked")


@pytest.fixture(autouse=True)
def no_shell_keys(monkeypatch):
    for env in (KEY, "S2_API_KEY"):
        monkeypatch.setenv(env, "unset")  # recorded, so a key a test saves is removed afterwards too
        monkeypatch.delenv(env)


@pytest.fixture
def gate():
    backend = GateKeyring()
    keyring.set_keyring(backend)  # the memory_keychain fixture puts the previous one back
    yield backend
    backend.gate.set()  # lets a call a test left waiting finish


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(credentials, "KEYCHAIN_TIMEOUT", 0.3)
    monkeypatch.setattr(credentials, "STARTUP_TIMEOUT", 0.4)


def make_client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", port=8765)
    app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))),
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
    c = TestClient(app)
    c.__enter__()
    c.headers["x-deixis-csrf"] = c.get("/api/session").json()["csrf_token"]
    return c


@pytest.fixture
def client(tmp_path):
    c = make_client(tmp_path)
    yield c
    c.__exit__(None, None, None)


def entry(client, env=KEY):
    return next(k for k in client.get("/api/credentials").json()["keys"] if k["env"] == env)


def wait_until(check, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def restart():
    """What a new process starts with: no state of this run, then the start-up read."""
    for env in credentials.MANAGED_KEYS:
        os.environ.pop(env, None)
    credentials._from_keychain.clear()
    credentials._session.clear()
    credentials.load_into_environment()


# ---- E5: a keychain that never answers or refuses --------------------------------------------------------------------
def test_a_keychain_that_never_answers_does_not_stop_the_start_or_the_api(gate, fast, client):
    gate.items[("DEIXIS", KEY)] = V1
    gate.close_for, _ = {"get", "set", "delete"}, gate.gate.clear()
    began = time.monotonic()
    credentials.load_into_environment()  # the start-up read gives up at its deadline
    assert time.monotonic() - began < 3
    assert entry(client)["keychain_unavailable"] is True and not entry(client)["configured"]
    assert client.get("/api/mathpix").status_code == 200  # other requests are answered
    # A change goes behind the stuck call, gives up, and was cancelled before it started: nothing to wait for.
    first = client.put(f"/api/credentials/{KEY}", json={"value": V2})
    assert first.status_code == 503 and first.json()["code"] == "keychain_not_responding" and V2 not in first.text
    assert client.put(f"/api/credentials/{KEY}", json={"value": V2}).json()["code"] == "keychain_not_responding"
    assert client.delete(f"/api/credentials/{KEY}").status_code == 503
    assert entry(client)["keychain_pending"] is False and not os.environ.get(KEY)


def test_a_refusing_keychain_starts_the_app_keyless_and_refuses_the_change(monkeypatch, client):
    keyring.set_keyring(RefusingKeyring())
    credentials.load_into_environment()
    assert entry(client)["keychain_unavailable"] is True
    refused = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert refused.status_code == 503 and "did not store" in refused.json()["detail"] and not os.environ.get(KEY)
    assert client.get("/api/credentials").status_code == 200


def test_a_write_that_finishes_late_is_read_back_and_never_overwrites_a_newer_change(gate, fast, client):
    gate.close_for, _ = {"set"}, gate.gate.clear()
    late = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert late.status_code == 503 and late.json()["code"] == "keychain_not_responding"
    assert entry(client)["keychain_pending"] is True and not entry(client)["configured"]
    # While the outcome is unknown a new change to the same key is refused, and a key that is not named is not touched.
    busy = client.put(f"/api/credentials/{KEY}", json={"value": V2})
    assert busy.status_code == 409 and busy.json()["code"] == "keychain_busy"
    assert client.delete(f"/api/credentials/{KEY}").json()["code"] == "keychain_busy"
    gate.close_for.clear()
    gate.gate.set()
    assert wait_until(lambda: not entry(client)["keychain_pending"])
    shown = entry(client)  # the keychain was read again: the late write did happen, and the app now says so
    assert shown["configured"] and shown["source"] == "keychain" and os.environ[KEY] == V1 and gate.items[("DEIXIS", KEY)] == V1
    assert client.put(f"/api/credentials/{KEY}", json={"value": V2}).status_code == 200  # after it, the newer change goes in
    assert gate.items[("DEIXIS", KEY)] == V2 and os.environ[KEY] == V2


def test_a_delete_that_finishes_late_removes_the_key_from_the_app(gate, fast, client):
    assert client.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 200
    gate.close_for, _ = {"delete"}, gate.gate.clear()
    assert client.delete(f"/api/credentials/{KEY}").status_code == 503
    assert os.environ[KEY] == V1  # not known to be removed yet
    gate.close_for.clear()
    gate.gate.set()
    assert wait_until(lambda: not entry(client)["keychain_pending"])
    assert not entry(client)["configured"] and not os.environ.get(KEY) and gate.items == {}


def test_every_keychain_call_runs_on_one_thread_in_turn(gate):
    seen = []

    def get_password(service, username, _real=gate.get_password):
        seen.append(threading.current_thread().name)
        return None

    gate.get_password = get_password
    credentials.load_into_environment()
    assert set(seen) == {"keychain"} and len(seen) == len([e for e in credentials.MANAGED_KEYS])


# ---- A6: no keychain backend -------------------------------------------------------------------------------------------
@pytest.fixture
def no_keychain():
    keyring.set_keyring(fail.Keyring())


def test_without_a_keychain_a_key_lasts_for_the_session_and_is_gone_after_a_restart(no_keychain, client):
    listed = client.get("/api/credentials").json()["keychain"]
    assert listed == {"available": False, "name": None, "mode": "session"}
    saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})  # was a 503 "No system keychain is available"
    assert saved.status_code == 200 and saved.json()["key"]["source"] == "session" and os.environ[KEY] == V1
    assert entry(client)["configured"] and V1 not in client.get("/api/credentials").text
    assert client.delete(f"/api/credentials/{KEY}").json()["key"]["configured"] is False and not os.environ.get(KEY)
    client.put(f"/api/credentials/{KEY}", json={"value": V2})
    assert credentials._session == {KEY: V2}
    restart()
    assert not os.environ.get(KEY) and not entry(client)["configured"]


def test_the_key_file_is_a_choice_kept_private_and_survives_a_restart(no_keychain, client, tmp_path):
    path = tmp_path / "data" / credentials.FILE_STORE
    client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert not path.exists()  # off unless chosen
    chosen = client.put("/api/credentials/file-store", json={"enabled": True})
    assert chosen.status_code == 200 and chosen.json()["keychain"]["mode"] == "file"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and json.loads(path.read_text())["keys"] == {KEY: V1}
    client.put("/api/credentials/S2_API_KEY", json={"value": "s2-source-good-key"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and set(json.loads(path.read_text())["keys"]) == {KEY, "S2_API_KEY"}
    restart()
    assert os.environ[KEY] == V1 and entry(client)["source"] == "file"
    client.delete(f"/api/credentials/{KEY}")
    assert json.loads(path.read_text())["keys"] == {"S2_API_KEY": "s2-source-good-key"}
    stopped = client.put("/api/credentials/file-store", json={"enabled": False})
    assert stopped.json()["keychain"]["mode"] == "session" and not path.exists()


def test_the_key_file_cannot_be_chosen_when_a_system_keychain_exists(client, tmp_path):
    refused = client.put("/api/credentials/file-store", json={"enabled": True})
    assert refused.status_code == 409 and refused.json()["code"] == "file_store_unavailable"
    assert not (tmp_path / "data" / credentials.FILE_STORE).exists()


def test_the_mathpix_pair_is_kept_for_the_session_without_a_keychain(no_keychain, tmp_path, monkeypatch):
    from deixis.documents import mathpix

    async def accepted(http, app_id, app_key):
        return {"status": "ok", "http_status": 200, "detail": "ok"}

    monkeypatch.setattr(mathpix, "test_pair", accepted)
    c = make_client(tmp_path)
    try:
        saved = c.put("/api/credentials/mathpix", json={"app_id": "synthetic-app", "app_key": "synthetic-key-0001"})
        assert saved.status_code == 200 and saved.json()["mathpix"]["pair"]["configured"] is True
        assert mathpix.ENV in credentials._session
        assert c.delete("/api/credentials/mathpix").status_code == 200 and credentials._session == {}
    finally:
        c.__exit__(None, None, None)
