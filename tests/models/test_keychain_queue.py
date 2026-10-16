"""The keychain queue and the key stores without a keychain (E5, A6).

The keychains here are fakes in memory (a gate that never opens, one that refuses, none at all). They show how the app
handles a keychain that does not answer or does not exist; they say nothing about how a real macOS, Windows or Secret
Service keychain behaves when locked or asked for a password.
"""

import asyncio
import json
import types
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
from keyring.compat import properties
from keyring.errors import PasswordDeleteError, PasswordSetError

from deixis.keys import credentials
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
def no_redetection(monkeypatch):
    """A keychain found unreachable is looked for again with keyring made to detect anew, which would pick the developer's
    real keychain; here that step only counts, and the next lookup comes at once."""
    calls = []
    monkeypatch.setattr(keyring.core, "init_backend", lambda limit=None: calls.append("init_backend"))
    monkeypatch.setattr(credentials, "RETRY_AFTER", 0.0)
    return calls


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
    assert refused.status_code == 503 and refused.json()["code"] == "keychain_locked" and not os.environ.get(KEY)
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


class DenyingDeleteKeyring(GateKeyring):
    """What keyring 25.7.0's macOS backend does with a refused, locked or cancelled delete: every keychain error becomes a
    PasswordDeleteError, the same type as for an item that is not there. The item stays."""

    def delete_password(self, service, username):
        if (service, username) not in self.items:
            raise PasswordDeleteError(username)
        try:
            raise OSError("User canceled the operation. (-128)")
        except OSError as cause:
            raise PasswordDeleteError("Can't delete password in keychain") from cause


def test_a_refused_delete_is_not_taken_for_an_absent_key(client):
    backend = DenyingDeleteKeyring()
    keyring.set_keyring(backend)
    assert client.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 200
    refused = client.delete(f"/api/credentials/{KEY}")
    assert refused.status_code == 503 and refused.json()["code"] == "keychain_denied"
    assert backend.items[("DEIXIS", KEY)] == V1 and os.environ[KEY] == V1 and entry(client)["configured"]
    del backend.items[("DEIXIS", KEY)]  # gone from the keychain by other means: the next removal finds nothing and succeeds
    assert client.delete(f"/api/credentials/{KEY}").status_code == 200 and not os.environ.get(KEY)


def test_a_second_save_while_the_first_waits_on_the_keychain_is_refused_and_the_shell_key_comes_back(gate, monkeypatch):
    monkeypatch.setenv(KEY, "shell-source-key-value")
    gate.close_for, _ = {"set"}, gate.gate.clear()

    async def two_saves():
        first = asyncio.get_running_loop().create_task(credentials.save_async(KEY, V1))
        while not gate.entered.is_set():
            await asyncio.sleep(0.01)
        with pytest.raises(credentials.KeychainBusy):
            await credentials.save_async(KEY, V2)
        with pytest.raises(credentials.KeychainBusy):
            await credentials.delete_async(KEY)
        gate.gate.set()
        await first

    asyncio.run(two_saves())
    assert os.environ[KEY] == V1 and credentials._shell_values == {KEY: "shell-source-key-value"}
    gate.close_for.clear()
    credentials.save(KEY, V2)  # once the first has finished, the next change goes in and keeps the shell key as it was
    credentials.delete(KEY)
    assert os.environ[KEY] == "shell-source-key-value"


def test_every_keychain_call_runs_on_one_thread_in_turn(gate, client):
    """Finding the backend, asking its priority, and reading, writing and deleting a key: all on the one worker thread."""
    seen = {}

    def note(call):
        seen.setdefault(call, set()).add(threading.current_thread().name)

    class Recording(GateKeyring):
        @properties.classproperty
        def priority(cls):
            note("priority")
            return 1

        def get_password(self, service, username):
            note("get")
            return super().get_password(service, username)

        def set_password(self, service, username, password):
            note("set")
            super().set_password(service, username, password)

        def delete_password(self, service, username):
            note("delete")
            super().delete_password(service, username)

    real_get_keyring = keyring.get_keyring

    def get_keyring():
        note("get_keyring")
        return real_get_keyring()

    try:
        keyring.set_keyring(Recording())
        keyring.get_keyring = get_keyring
        credentials._found_cache = None
        credentials.load_into_environment()  # start-up: discovery, priority, one read per key
        credentials.save(KEY, V1)
        credentials.delete(KEY)
        assert client.put(f"/api/credentials/{KEY}", json={"value": V2}).status_code == 200  # the API: same queue
        assert client.delete(f"/api/credentials/{KEY}").status_code == 200
        credentials._found_cache = None
        assert client.get("/api/credentials").status_code == 200  # discovery again, from the API
    finally:
        keyring.get_keyring = real_get_keyring
        KeyringBackend._classes.discard(Recording)
    assert seen.keys() == {"get_keyring", "priority", "get", "set", "delete"}
    assert all(names == {"keychain"} for names in seen.values()), seen


def test_a_discovery_that_never_returns_does_not_block_the_event_loop_or_the_start(fast, monkeypatch, tmp_path):
    release = threading.Event()

    def hang():
        release.wait(5)
        return fail.Keyring()

    monkeypatch.setattr(keyring, "get_keyring", hang)
    credentials._found_cache = None
    try:
        began = time.monotonic()
        credentials.load_into_environment()  # no event loop: gives up at the limit
        assert time.monotonic() - began < 2
        assert credentials.keychain_failed() and all(env in credentials._unavailable for env in credentials.MANAGED_KEYS)

        monkeypatch.setattr(credentials, "_worker", credentials._Worker())  # a worker not yet stuck: the loop has to wait for the limit

        async def inside_the_loop():
            lags = []

            async def ticker():
                while True:
                    before = time.monotonic()
                    await asyncio.sleep(0.005)
                    lags.append(time.monotonic() - before)

            task = asyncio.get_running_loop().create_task(ticker())
            await credentials.probe_async()
            credentials.keychain_name(), credentials.store_kind(), credentials.status(KEY)
            with pytest.raises(credentials.KeychainNotResponding):
                await credentials.save_async(KEY, V1)
            await asyncio.sleep(0.05)
            task.cancel()
            return max(lags)

        assert asyncio.run(inside_the_loop()) < 0.15  # the limit is 0.3 s; the loop never waited for it
        c = make_client(tmp_path)  # the app starts and answers
        try:
            began = time.monotonic()
            assert c.get("/api/credentials").status_code == 200 and c.get("/api/mathpix").status_code == 200
            assert time.monotonic() - began < 1
            refused = c.put(f"/api/credentials/{KEY}", json={"value": V1})
            assert refused.status_code == 503 and refused.json()["code"] == "keychain_not_responding"
        finally:
            c.__exit__(None, None, None)
        assert credentials._session == {} and not os.environ.get(KEY)
    finally:
        release.set()


class BrokenService(KeyringBackend):
    """A backend that is installed, but the desktop service behind it errors while keyring asks for its priority."""

    @properties.classproperty
    def priority(cls):
        raise OSError("could not connect to the secret service")

    def get_password(self, service, username):
        raise NotImplementedError

    set_password = delete_password = get_password


class UnbuildableService(KeyringBackend):
    """A backend that reports itself usable but cannot be built (keyring skips a TypeError from the constructor)."""

    priority = 5

    def __init__(self):
        raise TypeError("cannot build")

    def get_password(self, service, username):
        raise NotImplementedError

    set_password = delete_password = get_password


@pytest.fixture(autouse=True)
def only_while_a_test_uses_them():
    """Backends register themselves in keyring's list of classes; the broken ones are there only for the tests that ask."""
    for cls in (BrokenService, UnbuildableService, RecoveringService, FlakyAtFirstService):
        KeyringBackend._classes.discard(cls)
    yield
    for cls in (BrokenService, UnbuildableService, RecoveringService, FlakyAtFirstService):
        KeyringBackend._classes.discard(cls)


@pytest.mark.parametrize("broken", [BrokenService, UnbuildableService])
def test_a_keychain_that_errors_is_not_replaced_by_the_session_store(broken, client):
    KeyringBackend._classes.add(broken)
    keyring.set_keyring(fail.Keyring())  # what keyring picks after it dropped the broken backend
    credentials._found_cache = None
    assert credentials.keychain_failed() and credentials.keychain_name() is None
    refused = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert refused.status_code == 503 and refused.json()["code"] == "keychain_not_responding"
    assert credentials._session == {} and not os.environ.get(KEY) and V1 not in refused.text
    assert client.delete(f"/api/credentials/{KEY}").status_code == 503
    assert client.put("/api/credentials/file-store", json={"enabled": True}).status_code == 503
    assert client.get("/api/credentials").json()["keychain"]["available"] is False
    credentials.load_into_environment()
    assert entry(client)["keychain_unavailable"] is True  # shown as not answering, not as having no keys


def test_no_installed_backend_still_means_the_session_store(client):
    """keyring's own 'not available on this machine' (RuntimeError) and a missing backend are not an error."""

    class Absent(KeyringBackend):
        @properties.classproperty
        def priority(cls):
            raise RuntimeError("no secret service on this machine")

        def get_password(self, service, username):
            raise NotImplementedError

        set_password = delete_password = get_password

    try:
        keyring.set_keyring(fail.Keyring())
        credentials._found_cache = None
        assert not credentials.keychain_failed()
        saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
        assert saved.status_code == 200 and credentials._session == {KEY: V1}
    finally:
        KeyringBackend._classes.discard(Absent)


# ---- A6: no keychain backend -------------------------------------------------------------------------------------------
@pytest.fixture
def no_keychain():
    keyring.set_keyring(fail.Keyring())


def test_without_a_keychain_a_key_lasts_for_the_session_and_is_gone_after_a_restart(no_keychain, client):
    listed = client.get("/api/credentials").json()["keychain"]
    assert listed == {"available": False, "name": None, "kind": None, "mode": "session", "file_error": False}
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


# ---- A6: a key file that cannot be read is left as it is ---------------------------------------------------------------
@pytest.mark.parametrize("content", [b"{not json", b'{"keys": ["a list"]}', b"\xff\xfe binary", b"{}"])
def test_a_key_file_that_cannot_be_read_is_never_rewritten(no_keychain, tmp_path, content):
    data = tmp_path / "data"
    data.mkdir()
    path = data / credentials.FILE_STORE
    path.write_bytes(content)
    c = make_client(tmp_path)
    try:
        credentials.load_into_environment()  # the start-up read skips it
        assert c.get("/api/credentials").json()["keychain"]["file_error"] is True
        for refused in (c.put(f"/api/credentials/{KEY}", json={"value": V1}), c.delete(f"/api/credentials/{KEY}"),
                        c.put("/api/credentials/file-store", json={"enabled": False}), c.put("/api/credentials/file-store", json={"enabled": True})):
            assert refused.status_code == 409 and refused.json()["code"] == "file_store_damaged"
        assert path.read_bytes() == content and credentials._session == {} and not os.environ.get(KEY)
        assert not list(data.glob(".keys.*"))  # no temporary file left behind
    finally:
        c.__exit__(None, None, None)


def test_a_key_file_that_is_repaired_is_read_before_the_next_change(no_keychain, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    path = data / credentials.FILE_STORE
    path.write_text("{broken")
    c = make_client(tmp_path)
    try:
        assert c.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 409
        path.write_text(json.dumps({"keys": {"S2_API_KEY": "s2-source-good-key"}}))  # the person fixed it
        assert c.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 200
        assert json.loads(path.read_text())["keys"] == {"S2_API_KEY": "s2-source-good-key", KEY: V1}  # the earlier key is kept
        assert c.get("/api/credentials").json()["keychain"]["file_error"] is False
    finally:
        c.__exit__(None, None, None)


def test_a_key_the_file_could_not_take_is_not_saved_by_a_later_change(no_keychain, client, tmp_path, monkeypatch):
    path = tmp_path / "data" / credentials.FILE_STORE
    assert client.put("/api/credentials/file-store", json={"enabled": True}).status_code == 200
    assert client.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 200

    def full(keys=None):
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as refusing:
        refusing.setattr(credentials, "_write_file_store", full)
        assert client.put(f"/api/credentials/{KEY}", json={"value": V2}).json()["code"] == "file_write_failed"
        assert client.delete(f"/api/credentials/{KEY}").json()["code"] == "file_write_failed"
    assert credentials._session == {KEY: V1} and os.environ[KEY] == V1
    assert client.put("/api/credentials/S2_API_KEY", json={"value": "s2-source-good-key"}).status_code == 200
    assert json.loads(path.read_text())["keys"] == {KEY: V1, "S2_API_KEY": "s2-source-good-key"}  # neither V2 nor a removal


# ---- E5: what a failed Secret Service connection means (keyring 25.7.0 wraps it in RuntimeError) -------------------------
class FakeStorageError(Exception):
    pass


class FakeConnection:
    def close(self):
        pass


def fake_secretstorage(monkeypatch, dbus_init=lambda: FakeConnection(), available=lambda connection: True):
    """The real keyring Secret Service backend, with the `secretstorage` module it imports replaced at that level."""
    from keyring.backends import SecretService

    module = types.SimpleNamespace(__name__="secretstorage", __version_tuple__=(3, 5, 0), dbus_init=dbus_init,
                                   check_service_availability=available)
    monkeypatch.setattr(SecretService, "secretstorage", module, raising=False)
    monkeypatch.setattr(SecretService, "exceptions", types.SimpleNamespace(SecretStorageException=FakeStorageError), raising=False)


def raises(error, cause=None):
    def raiser(*args):
        if cause is not None:
            raise error from cause
        raise error
    return raiser


def no_session_bus():
    raise FakeStorageError("Environment variable DBUS_SESSION_BUS_ADDRESS is unset") from KeyError("DBUS_SESSION_BUS_ADDRESS")


def refused_connection():
    raise FakeStorageError("[Errno 61] Connection refused") from ConnectionRefusedError(61, "Connection refused")


@pytest.mark.parametrize("dbus_init, available, bus_address", [
    (no_session_bus, None, "unix:path=/run/user/1000/bus"),  # no address in the environment of the process: no desktop session
    (refused_connection, None, None),  # no session bus address at all
    (lambda: FakeConnection(), lambda connection: False, "unix:path=/run/user/1000/bus"),  # neither running nor activatable
])
def test_a_secret_service_that_is_not_there_means_the_session_store(monkeypatch, client, dbus_init, available, bus_address):
    fake_secretstorage(monkeypatch, dbus_init, available or (lambda connection: True))
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    if bus_address and dbus_init is not no_session_bus:
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", bus_address)
    keyring.set_keyring(fail.Keyring())
    credentials._found_cache = None
    assert not credentials.keychain_failed()
    saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert saved.status_code == 200 and saved.json()["key"]["source"] == "session" and credentials._session == {KEY: V1}


def check_raises_timeout(connection):
    raise FakeStorageError("timed out waiting for the Secret Service") from TimeoutError()


@pytest.mark.parametrize("dbus_init, available", [
    (refused_connection, lambda connection: True),  # the bus address is set and the connection fails
    (lambda: FakeConnection(), check_raises_timeout),  # connected, and the service errors while it is asked
])
def test_a_secret_service_that_is_there_and_errors_is_not_replaced_by_the_session_store(monkeypatch, client, dbus_init, available):
    fake_secretstorage(monkeypatch, dbus_init, available)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    keyring.set_keyring(fail.Keyring())
    credentials._found_cache = None
    assert credentials.keychain_failed()
    refused = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert refused.status_code == 503 and refused.json()["code"] == "keychain_not_responding"
    assert credentials._session == {} and not os.environ.get(KEY)


def test_a_keychain_found_unreachable_is_looked_for_again_and_a_service_that_recovers_is_used(monkeypatch, client, no_redetection):
    service_up = []
    fake_secretstorage(monkeypatch, lambda: FakeConnection() if service_up else refused_connection())
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    keyring.set_keyring(fail.Keyring())  # keyring's choice when it first looked, and it keeps that choice
    credentials._found_cache = None
    resets = []
    monkeypatch.setattr(keyring.backend.get_all_keyring, "reset", lambda: resets.append(1), raising=False)
    monkeypatch.setattr(credentials, "RETRY_AFTER", 60.0)
    assert client.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 503
    assert no_redetection == []  # the first look needs no fresh detection
    credentials._failed_at -= 61  # the wait is over
    working = GateKeyring()

    def detect_anew(limit=None):
        no_redetection.append("init_backend")
        keyring.set_keyring(working)  # what keyring finds once the service answers

    monkeypatch.setattr(keyring.core, "init_backend", detect_anew)
    service_up.append(1)
    saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert saved.status_code == 200 and saved.json()["key"]["source"] == "keychain" and working.items[("DEIXIS", KEY)] == V1
    assert no_redetection == ["init_backend"] and resets == [1] and credentials._session == {}


def test_a_keychain_found_unreachable_is_looked_for_again_only_every_so_often(monkeypatch, client, no_redetection):
    monkeypatch.setattr(credentials, "RETRY_AFTER", 60.0)
    monkeypatch.setattr(keyring.core, "init_backend", lambda limit=None: no_redetection.append("init_backend"))
    fake_secretstorage(monkeypatch, refused_connection)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    keyring.set_keyring(fail.Keyring())
    credentials._found_cache = None
    for _ in range(3):
        assert client.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 503
    assert no_redetection == []  # inside the wait: no new look
    credentials._failed_at -= 61
    assert client.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 503
    assert no_redetection == ["init_backend"]


# ---- E5: a keychain found after the start read none of its keys ---------------------------------------------------------
def test_a_keychain_found_after_the_start_has_its_saved_keys_read(gate, fast, monkeypatch, tmp_path):
    gate.items[("DEIXIS", KEY)] = V1
    release = threading.Event()
    real = keyring.get_keyring

    def hang():
        release.wait(5)
        return real()

    monkeypatch.setattr(keyring, "get_keyring", hang)
    credentials._found_cache = None
    credentials.load_into_environment()  # the start: discovery timed out
    c = make_client(tmp_path)
    try:
        assert entry(c)["keychain_unavailable"] is True and not entry(c)["configured"]
        release.set()
        monkeypatch.setattr(keyring, "get_keyring", real)  # the keychain answers from now on
        assert wait_until(lambda: credentials._worker.running_since is None)
        shown = entry(c)  # the next request finds it and reads the keys, as the start does
        assert shown["configured"] and shown["source"] == "keychain" and shown["keychain_unavailable"] is False
        assert os.environ[KEY] == V1 and credentials._keys_pending is False
    finally:
        c.__exit__(None, None, None)


def test_a_keychain_found_after_the_start_has_its_keys_read_outside_the_api_too(gate, fast, monkeypatch):
    gate.items[("DEIXIS", KEY)] = V1
    release = threading.Event()
    real = keyring.get_keyring

    def hang():
        release.wait(5)
        return real()

    monkeypatch.setattr(keyring, "get_keyring", hang)
    credentials._found_cache = None
    credentials.load_into_environment()
    assert not os.environ.get(KEY) and credentials._keys_pending
    release.set()
    monkeypatch.setattr(keyring, "get_keyring", real)
    assert wait_until(lambda: credentials._worker.running_since is None)
    assert credentials.keychain_name() is not None and os.environ[KEY] == V1 and KEY not in credentials._unavailable


# ---- D29: a shell key is replaced only where a keychain holds the replacement -------------------------------------------
def test_a_shell_key_cannot_be_replaced_without_a_system_keychain(no_keychain, client, monkeypatch):
    monkeypatch.setenv(KEY, "shell-source-key-value")
    refused = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert refused.status_code == 409 and refused.json()["code"] == "shell_key_stays"
    assert os.environ[KEY] == "shell-source-key-value" and credentials._session == {} and entry(client)["source"] == "environment"
    other = client.put("/api/credentials/S2_API_KEY", json={"value": "s2-source-good-key"})
    assert other.status_code == 200 and other.json()["key"]["source"] == "session"  # a key that is not from the shell still can


def test_a_shell_key_is_replaced_when_a_system_keychain_holds_the_replacement(client, monkeypatch):
    monkeypatch.setenv(KEY, "shell-source-key-value")
    replaced = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert replaced.status_code == 200 and replaced.json()["key"]["source"] == "keychain" and os.environ[KEY] == V1


class RecoveringService(KeyringBackend):
    """A backend whose service errors at first and answers later, while keyring keeps the `fail.Keyring` it chose."""

    up = False
    items: dict = {}

    @properties.classproperty
    def priority(cls):
        if not cls.up:
            raise OSError("the secret service is not answering")
        return 9

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        self.items.pop((service, username), None)


def test_a_backend_that_answers_on_the_second_look_is_used_not_cached_as_no_keychain(client, monkeypatch):
    monkeypatch.setattr(credentials, "_chosen_on_purpose", lambda: False)
    RecoveringService.up, RecoveringService.items = False, {}
    KeyringBackend._classes.add(RecoveringService)
    try:
        keyring.set_keyring(fail.Keyring())  # keyring's choice from the first look, kept by keyring
        credentials._found_cache = None
        assert client.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 503  # the first look: it errored
        assert credentials._failed_at is not None and credentials._session == {}
        RecoveringService.up = True  # the second look: the same backend answers, keyring's choice is still fail.Keyring
        saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
        assert saved.status_code == 200 and saved.json()["key"]["source"] == "keychain"
        assert credentials._session == {} and RecoveringService.items == {("DEIXIS", KEY): V1}
        assert isinstance(keyring.get_keyring(), RecoveringService) and credentials._failed_at is None
    finally:
        KeyringBackend._classes.discard(RecoveringService)


def test_a_backend_that_still_cannot_be_built_on_the_second_look_stays_retryable(client):
    KeyringBackend._classes.add(UnbuildableService)
    keyring.set_keyring(fail.Keyring())
    credentials._found_cache = None
    for _ in range(2):
        assert client.put(f"/api/credentials/{KEY}", json={"value": V1}).status_code == 503
        assert credentials._failed_at is not None and credentials._found_cache is None and credentials._session == {}


REAL_CHOSEN_ON_PURPOSE = credentials._chosen_on_purpose  # read at import, before the conftest fixture replaces it


class FlakyAtFirstService(RecoveringService):
    """Errors only on keyring's own first look, answers when DEIXIS asks again in the same discovery."""

    calls = 0

    @properties.classproperty
    def priority(cls):
        cls.calls += 1
        if cls.calls == 1:
            raise OSError("the secret service is not answering yet")
        return 9


def test_a_backend_that_answers_within_the_first_discovery_is_used_not_cached_as_no_keychain(client, monkeypatch):
    monkeypatch.setattr(credentials, "_chosen_on_purpose", REAL_CHOSEN_ON_PURPOSE)
    monkeypatch.delenv("PYTHON_KEYRING_BACKEND")
    monkeypatch.setattr(keyring.core, "load_config", lambda: None)
    FlakyAtFirstService.calls, FlakyAtFirstService.items = 1, {}  # keyring's own look already hit the error
    KeyringBackend._classes.add(FlakyAtFirstService)
    try:
        keyring.set_keyring(fail.Keyring())  # what keyring kept after that error
        credentials._found_cache = None
        saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
        assert saved.status_code == 200 and saved.json()["key"]["source"] == "keychain"
        assert credentials._session == {} and FlakyAtFirstService.items == {("DEIXIS", KEY): V1}
    finally:
        KeyringBackend._classes.discard(FlakyAtFirstService)


def test_a_configured_fail_keyring_is_kept_even_when_a_backend_answers(client, monkeypatch):
    monkeypatch.setattr(credentials, "_chosen_on_purpose", REAL_CHOSEN_ON_PURPOSE)
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
    RecoveringService.up, RecoveringService.items = True, {}
    KeyringBackend._classes.add(RecoveringService)
    try:
        keyring.set_keyring(fail.Keyring())
        credentials._found_cache = None
        saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
        assert saved.status_code == 200 and saved.json()["key"]["source"] == "session" and RecoveringService.items == {}
    finally:
        KeyringBackend._classes.discard(RecoveringService)
