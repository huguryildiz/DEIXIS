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


def pytest_configure(config):
    config.addinivalue_line("markers", "field_distribution: the test's own transport answers the routing request (D93)")


@pytest.fixture(autouse=True)
def no_field_distribution(request, monkeypatch):
    """The source routing request of an sw run (D93) reads no distribution unless a test is about it.

    An unread distribution routes to every domain source in scope, which is the search every test written before
    slice 14 expects, and no mocked OpenAlex has to tell a grouped request from a search. A test marked
    `field_distribution` sends the request through its own transport.
    """
    if request.node.get_closest_marker("field_distribution"):
        return
    from deixis.providers import openalex

    async def unread(*args, **kwargs):
        return None

    monkeypatch.setattr(openalex, "field_distribution", unread)
