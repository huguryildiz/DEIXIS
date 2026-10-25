"""The keychain queue: a hung or failing keychain, late writes, the session store and the key file, and refused
changes named by cause.

Scripted keyring backends; the real keychain is never touched. Passing shows the queue's behaviour with them.
"""

import httpx
import json
import keyring
import os
import pytest
import threading
import time
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.compat import properties
from keyring.errors import KeyringLocked
from keyring.errors import PasswordDeleteError
from keyring.errors import PasswordSetError

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.keys import credentials
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


@pytest.mark.parametrize("broken", [BrokenService])
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


# ---- A6: no keychain backend -------------------------------------------------------------------------------------------
@pytest.fixture
def no_keychain():
    keyring.set_keyring(fail.Keyring())


# ---- A6: a key file that cannot be read is left as it is ---------------------------------------------------------------
@pytest.mark.parametrize("content", [b"{not json"])
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


# ---- E5: what a failed Secret Service connection means (keyring 25.7.0 wraps it in RuntimeError) -------------------------


def raises(error, cause=None):
    def raiser(*args):
        if cause is not None:
            raise error from cause
        raise error
    return raiser


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


class FlakyAtFirstService(RecoveringService):
    """Errors only on keyring's own first look, answers when DEIXIS asks again in the same discovery."""

    calls = 0

    @properties.classproperty
    def priority(cls):
        cls.calls += 1
        if cls.calls == 1:
            raise OSError("the secret service is not answering yet")
        return 9


CLASS_NAMES = ("PasswordSetError", "PasswordDeleteError", "KeyringError", "KeyringLocked", "OSError", "PermissionError",
               "RuntimeError", "Traceback", "Errno", ".env")


class Scripted(KeyringBackend):
    """A keychain that reads fine and refuses every change with `error`."""

    priority = 1

    def __init__(self, error=None):
        super().__init__()
        self.error = error

    def get_password(self, service, username):
        return None

    def set_password(self, service, username, password):
        raise self.error

    def delete_password(self, service, username):
        raise self.error


@pytest.fixture(autouse=True)
def scripted_is_not_a_registered_backend():
    """Backends register themselves with keyring; this one is wanted only where a test sets it."""
    KeyringBackend._classes.discard(Scripted)
    yield
    KeyringBackend._classes.discard(Scripted)


def windows_size_error():
    cause = Exception(1783, "CredWrite", "The stub received bad data.")
    error = PasswordSetError("Can't store password on keychain")
    error.__cause__ = cause
    return error


CAUSES = [
    ("keychain_too_large", lambda: PasswordSetError("password too long for this keychain")),
    ("keychain_too_large", windows_size_error),
    ("keychain_locked", lambda: KeyringLocked("Failed to unlock the collection!")),
    ("keychain_denied", lambda: KeyringLocked("User canceled the operation. (-128)")),  # macOS: the person's own "Deny", wrapped as locked
    ("keychain_locked", lambda: PasswordSetError("Cannot create an item in a locked collection")),
    ("keychain_denied", lambda: PermissionError(13, "Permission denied")),
    ("keychain_denied", lambda: PasswordSetError("Access denied by the user")),
    ("keychain_unavailable", lambda: PasswordSetError("SYNTHETIC unexplained failure")),
    ("keychain_unavailable", lambda: RuntimeError("SYNTHETIC not a keyring error at all")),
]


@pytest.mark.parametrize("code,make", CAUSES[:1])
def test_a_refused_keychain_change_names_its_cause_and_no_exception(code, make, client, caplog):
    keyring.set_keyring(Scripted(make()))
    credentials._found_cache = None
    with caplog.at_level("WARNING", logger="deixis.keys.credentials"):
        saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
        removed = client.delete(f"/api/credentials/{KEY}")
    for response in (saved, removed):
        assert response.status_code == 503 and response.json() == {"code": code, "detail": credentials.FAILURES[code]}
        assert V1 not in response.text and not any(name in response.text for name in CLASS_NAMES)
    assert not os.environ.get(KEY) and entry(client)["configured"] is False
    assert type(make()).__name__ in caplog.text  # the class goes to the log, not to the response


def test_a_key_set_outside_the_app_is_refused_without_naming_the_variable(no_keychain, client, monkeypatch):  # noqa: F811
    monkeypatch.setenv(KEY, "shell-source-key-value")
    removed = client.delete(f"/api/credentials/{KEY}")
    assert removed.status_code == 409 and removed.json()["code"] == "shell_key" and KEY not in removed.text
    refused = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert refused.status_code == 409 and refused.json()["code"] == "shell_key_stays" and KEY not in refused.text
