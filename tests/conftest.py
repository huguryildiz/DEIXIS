import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from deixis import credentials


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.items = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        if self.items.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


@pytest.fixture(autouse=True)
def no_model_api_keys(monkeypatch):
    """Tests never use real model API keys; a test that needs one sets a fake key."""
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        # setenv first records the original value, so a key a test saves through the app is removed afterwards too.
        monkeypatch.setenv(name, "unset")
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def memory_keychain(monkeypatch):
    """Tests never read or write the real system keychain."""
    previous, backend = keyring.get_keyring(), MemoryKeyring()
    keyring.set_keyring(backend)
    monkeypatch.setattr(credentials, "_from_keychain", set())
    monkeypatch.setattr(credentials, "_from_dotenv", set())
    monkeypatch.setattr(credentials, "dotenv_path", None)
    yield backend
    keyring.set_keyring(previous)
