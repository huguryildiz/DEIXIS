from pathlib import Path

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


@pytest.fixture(scope="session", autouse=True)
def migrated_template(tmp_path_factory):
    """Running all 71 migrations costs about 0.1 s per new library and was close to half of the suite's time. Each
    worker migrates one template library once; an empty library migrated from the real migrations folder is then a
    page copy of it (sqlite backup). A test that points MIGRATIONS_DIR elsewhere, or a library that already has
    tables, goes through the real migrate."""
    from deixis.storage import db

    real_migrate, real_dir = db.migrate, db.MIGRATIONS_DIR
    template = db.connect(tmp_path_factory.mktemp("template") / "library.sqlite")
    versions = real_migrate(template)

    def migrate(conn):
        if db.MIGRATIONS_DIR != real_dir or conn.in_transaction or conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
            return real_migrate(conn)
        template.backup(conn)
        return list(versions)

    patch = pytest.MonkeyPatch()
    patch.setattr(db, "migrate", migrate)
    yield
    patch.undo()
    template.close()


@pytest.fixture(autouse=True)
def no_model_api_keys(monkeypatch):
    """Tests never use real model API keys; a test that needs one sets a fake key."""
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY", "MISTRAL_API_KEY"):
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
    config.addinivalue_line("markers", "process: starts and kills real processes (P9 H2); run with -m process -n 0")
    config.addinivalue_line("markers", "slow: listed in tests/slow_tests.txt; left out of a run with no -m and no path")
    config.addinivalue_line("markers", "provider_pacing: the test keeps the real arXiv and Semantic Scholar request gaps")


SLOW_TESTS = Path(__file__).with_name("slow_tests.txt")


def pytest_collection_modifyitems(config, items):
    """Process tests (tests/process) are wall-clock and start real servers: they run only when -m names `process`.

    Tests listed in slow_tests.txt (0.5 s or more each, about 960 of them) are marked `slow` and left out of a run that
    names no `-m` and no path, so the default run stays near a minute and a half. Naming a file or test, or any `-m`
    expression, runs them too; run everything before a push with `pytest -m "slow or not slow"`. To regenerate the list,
    run that with `--durations=0 --durations-min=0.3`, sum call + setup + teardown per test id, keep those at 0.5 s or more."""
    marker = config.getoption("-m") or ""
    slow = set(line for line in SLOW_TESTS.read_text().splitlines() if line and not line.startswith("#"))
    for item in items:
        if item.nodeid in slow:
            item.add_marker(pytest.mark.slow)
    if not marker and not config.getoption("file_or_dir"):
        slow_items = [item for item in items if item.get_closest_marker("slow")]
        if slow_items:
            config.hook.pytest_deselected(items=slow_items)
            items[:] = [item for item in items if not item.get_closest_marker("slow")]
    if "process" in marker:
        return
    skipped = [item for item in items if item.get_closest_marker("process")]
    if skipped:
        config.hook.pytest_deselected(items=skipped)
        items[:] = [item for item in items if item not in skipped]


@pytest.fixture(autouse=True)
def no_provider_pacing(request, monkeypatch):
    """arXiv's 3 s and Semantic Scholar's 2 s request gaps are real time; a test not about them does not wait them out."""
    if request.node.get_closest_marker("provider_pacing"):
        return
    from deixis.providers import arxiv, pacing

    monkeypatch.setattr(arxiv, "MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(pacing.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)


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


# The real uv, found before any test puts a fake one first on PATH.
import shutil as _shutil  # noqa: E402

_REAL_UV = _shutil.which("uv")


@pytest.fixture(autouse=True)
def builtin_embedding_guard(request, monkeypatch):
    """Slice 21: the built-in embedding tests never reach the network, the real uv or the real fastembed.

    For the `test_builtin_embedding_*` modules only: an httpx request that does not go through a mock transport, and a
    subprocess started with the real uv binary, fail the test."""
    if not request.module.__name__.startswith("test_builtin_embedding"):
        return
    import asyncio
    import os
    import subprocess

    import httpx

    def no_network(*args, **kwargs):
        raise AssertionError("a built-in embedding test sent a request that did not go through a mock transport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_network)

    def is_real_uv(program) -> bool:
        if _REAL_UV is None or program is None:
            return False
        found = _shutil.which(str(program)) or str(program)
        return os.path.realpath(found) == os.path.realpath(_REAL_UV)

    real_exec, real_popen = asyncio.create_subprocess_exec, subprocess.Popen.__init__

    async def guarded_exec(program, *args, **kwargs):
        assert not is_real_uv(program), "a built-in embedding test started the real uv"
        return await real_exec(program, *args, **kwargs)

    def guarded_popen(self, args, *rest, **kwargs):
        program = args[0] if isinstance(args, (list, tuple)) else str(args).split()[0]
        assert not is_real_uv(program), "a built-in embedding test started the real uv"
        return real_popen(self, args, *rest, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", guarded_exec)
    monkeypatch.setattr(subprocess.Popen, "__init__", guarded_popen)
