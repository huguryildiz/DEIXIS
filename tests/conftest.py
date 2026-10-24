import os
import sys
import tempfile
from pathlib import Path

# With PYTHONDONTWRITEBYTECODE set (it keeps __pycache__ out of a synced folder) every worker and every Python process a
# test starts compiled the whole package and re-wrote every test module's asserts: about 16 s of CPU each instead of 4.
# Compiled files go to a folder outside the repository instead; workers and child processes inherit the setting.
if os.environ.pop("PYTHONDONTWRITEBYTECODE", None):
    os.environ.setdefault("PYTHONPYCACHEPREFIX", str(Path(tempfile.gettempdir()) / "deixis-pycache"))
    sys.pycache_prefix = os.environ["PYTHONPYCACHEPREFIX"]
    sys.dont_write_bytecode = False

# Processes a test starts (CLI runs, helper scripts) inherit this and see no keychain, so they never read the developer's
# keys or move `.env` keys into the real keychain (D19). In this process `memory_keychain` sets its own backend.
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from deixis.keys import credentials, key_verification


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
def shared_route_adapters():
    """Most API tests build their own app, and FastAPI builds a pydantic TypeAdapter for every parameter and response of
    its ~240 routes each time: about half of `create_app`'s 0.14 s of CPU. The request and response models live at module
    level, so a parameter of the same type and options in the next app gets the adapter already built."""
    from fastapi._compat import v2

    real, built = v2.TypeAdapter, {}

    def adapter(type_, *, config=None):
        key = (repr(type_), repr(config))
        if key not in built:
            built[key] = real(type_, config=config)
        return built[key]

    patch = pytest.MonkeyPatch()
    patch.setattr(v2, "TypeAdapter", adapter)
    yield
    patch.undo()


@pytest.fixture(scope="session", autouse=True)
def migrated_template(tmp_path_factory):
    """Migrating every new library was close to half of the suite's time when the schema was a chain of 71 files. Each
    worker makes one template library from schema.sql once; an empty library is then a page copy of it (sqlite backup).
    A test that sets its own schema or upgrade steps (db.SCHEMA, upgrades.STEPS), or a library that already has tables,
    goes through the real migrate."""
    from deixis.storage import db, upgrades

    real_migrate, real_schema, real_steps = db.migrate, db.SCHEMA, upgrades.STEPS
    template = db.connect(tmp_path_factory.mktemp("template") / "library.sqlite")
    versions = real_migrate(template)

    def migrate(conn):
        if (db.SCHEMA != real_schema or upgrades.STEPS is not real_steps or conn.in_transaction
                or conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()):
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
    """Tests never use real model or source keys (every key Settings manages, OPENALEX_API_KEY included, plus
    GITHUB_TOKEN); a test that needs one sets a fake key."""
    for name in sorted(set(credentials.MANAGED_KEYS) | {"GITHUB_TOKEN"}):
        # setenv first records the original value, so a key a test saves through the app is removed afterwards too.
        monkeypatch.setenv(name, "unset")
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def no_repository_dotenv(monkeypatch):
    """`load_settings()` fills unset variables from the repository's own `.env`, which holds the developer's real keys, and
    those stay in the worker's environment for every later test (an OPENALEX_API_KEY turned a later keyless OpenAlex 401
    into a keyed one). Tests never read that file; a test that needs a `.env` writes its own."""
    from deixis import config
    from deixis.paths import RESOURCE_ROOT

    real, repository = config.load_dotenv, (RESOURCE_ROOT / ".env").resolve()
    monkeypatch.setattr(config, "load_dotenv", lambda path: set() if Path(path).resolve() == repository else real(path))


@pytest.fixture(autouse=True)
def no_real_platform_data_dir(monkeypatch, tmp_path_factory):
    """The platform default folder holds the location pointer (D32); tests never read or write the real one. A test
    that needs a pointer patches `config.platform_data_dir` to its own temp folder."""
    from deixis import config

    monkeypatch.setattr(config, "platform_data_dir", lambda: tmp_path_factory.getbasetemp() / "no-platform-default")


@pytest.fixture(autouse=True)
def no_held_folder_locks():
    """A `serve` or command line run inside a test takes its data folder's shared lock for the process (E1); it is
    let go after the test so no descriptor outlives it."""
    from deixis.storage import library_lock

    yield
    library_lock.release_all()


@pytest.fixture(autouse=True)
def no_registered_builtin_model(monkeypatch):
    """The built-in model's integrity is registered module-wide by an app; with nothing saved, a ready model is the
    default (D7), so one test's app never leaks it into another test."""
    from deixis.documents import local_embedding

    monkeypatch.setattr(local_embedding, "_registered", None)


@pytest.fixture(autouse=True)
def tools_only_on_path(monkeypatch):
    """`find_tool` (A3) also looks in the usual install folders and the login shell's PATH; in tests only PATH counts, so
    a test's fake tool (or its absence) is what the app sees, never a real CLI in /opt/homebrew/bin or ~/.local/bin.
    The tests of those fallbacks patch them back in."""
    from deixis.tools import tool_paths

    nothing = lambda: []  # noqa: E731
    nothing.real = tool_paths.known_places  # for the test of the list itself
    monkeypatch.setattr(tool_paths, "known_places", nothing)
    monkeypatch.setattr(tool_paths, "_shell_path", [])

    # The same for the places an installer puts an app (B1): only the tool's own `app` field counts (None in most tests),
    # never the Applications, Program Files or Flatpak folders of the computer running the tests.
    from deixis.tools import local_tools

    only_app = lambda tool: [Path(tool.app)] if tool.app else []  # noqa: E731
    only_app.real = local_tools.app_locations
    monkeypatch.setattr(local_tools, "app_locations", only_app)


@pytest.fixture(autouse=True)
def fake_tools_see_their_switches(monkeypatch):
    """The fake `uv`, runner and installer scripts of the tests read FAKE_* switches from their environment, which the
    child allowlist (A5) would otherwise drop. A key or token never has that prefix."""
    from deixis.tools import child_env

    monkeypatch.setattr(child_env, "OS_PREFIXES", ("LC_", "FAKE_"))


@pytest.fixture(autouse=True)
def memory_keychain(monkeypatch):
    """Tests never read or write the real system keychain."""
    previous, backend = keyring.get_keyring(), MemoryKeyring()
    keyring.set_keyring(backend)
    monkeypatch.setattr(credentials, "_from_keychain", set())
    monkeypatch.setattr(credentials, "_from_dotenv", set())
    monkeypatch.setattr(credentials, "_shell_values", {})
    monkeypatch.setattr(credentials, "_broken", set())
    monkeypatch.setattr(credentials, "_unavailable", set())
    monkeypatch.setattr(credentials, "_session", {})
    monkeypatch.setattr(credentials, "_settling", {})
    monkeypatch.setattr(credentials, "_changing", set())
    monkeypatch.setattr(credentials, "_data_dir", None)
    monkeypatch.setattr(credentials, "_worker", credentials._Worker())  # a keychain call a test leaves stuck belongs to that test
    monkeypatch.setattr(credentials, "_found_cache", None)
    monkeypatch.setattr(credentials, "_failed_at", None)
    monkeypatch.setattr(credentials, "_keys_pending", False)
    # a test that sets fail.Keyring means "no keychain", while its own fake backends stay registered with keyring
    monkeypatch.setattr(credentials, "_chosen_on_purpose", lambda: True)
    monkeypatch.setattr(key_verification, "_state", {})
    monkeypatch.setattr(credentials, "dotenv_path", None)
    yield backend
    keyring.set_keyring(previous)


def pytest_configure(config):
    config.addinivalue_line("markers", "field_distribution: the test's own transport answers the routing request (D93)")
    config.addinivalue_line("markers", "process: starts and kills real processes (P9 H2); run with -m process -n 0")
    config.addinivalue_line("markers", "slow: listed in tests/slow_tests.txt; left out of a run with no -m and no path")
    config.addinivalue_line("markers", "provider_pacing: the test keeps the real arXiv, Semantic Scholar and OpenAlex semantic request gaps")


SLOW_TESTS = Path(__file__).with_name("slow_tests.txt")


def pytest_collection_modifyitems(config, items):
    """Process tests (tests/process) are wall-clock and start real servers: they run only when -m names `process`.

    Tests listed in slow_tests.txt (0.2 s or more each, about 3,000 of them) are marked `slow` and left out of a run that
    names no `-m` and no path, so the default run stays within a minute or two on four workers. Naming a file or test, or
    any `-m` expression, runs them too; run everything before a push with `pytest -m "slow or not slow"`. To bring the
    list up to date, run that once with `--testmon`, then `uv run python scripts/update_slow_tests.py`."""
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
    if "process" not in marker:
        skipped = [item for item in items if item.get_closest_marker("process")]
        if skipped:
            config.hook.pytest_deselected(items=skipped)
            items[:] = [item for item in items if item not in skipped]
    keep_shard(config, items, slow)


def keep_shard(config, items, slow):
    """DEIXIS_TEST_SHARD=i/n keeps the i-th of n parts (from 0), so CI runs the full suite on n machines at once.

    Whole modules go to the lightest part, heaviest first, weighing a slow test as 1 and any other as 0.02; every machine
    collects the same tests and so makes the same split."""
    shard = os.environ.get("DEIXIS_TEST_SHARD")
    if not shard:
        return
    index, count = (int(part) for part in shard.split("/"))
    weights: dict[str, float] = {}
    for item in items:
        module = item.nodeid.split("::")[0]
        weights[module] = weights.get(module, 0.0) + (1.0 if item.nodeid in slow else 0.02)
    loads, owner = [0.0] * count, {}
    for module in sorted(weights, key=lambda m: (-weights[m], m)):
        lightest = loads.index(min(loads))
        owner[module], loads[lightest] = lightest, loads[lightest] + weights[module]
    other = [item for item in items if owner[item.nodeid.split("::")[0]] != index]
    if other:
        config.hook.pytest_deselected(items=other)
        items[:] = [item for item in items if owner[item.nodeid.split("::")[0]] == index]


@pytest.fixture(autouse=True)
def no_provider_pacing(request, monkeypatch):
    """arXiv's 3 s, Semantic Scholar's 2 s and OpenAlex semantic search's 1.5 s request gaps are real time; a test not
    about them does not wait them out."""
    if request.node.get_closest_marker("provider_pacing"):
        return
    from deixis.providers import arxiv, openalex, pacing

    monkeypatch.setattr(arxiv, "MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(pacing.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)
    monkeypatch.setattr(openalex.SEMANTIC_PACER, "interval_seconds", 0.0)
    monkeypatch.setattr(openalex.SEMANTIC_PACER, "_next", 0.0)


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


@pytest.fixture(autouse=True)
def builtin_embedding_guard(request, monkeypatch):
    """The built-in model tests never reach the network or a real llama.cpp build.

    For the `test_builtin_embedding_*` and `test_llama_*` modules only: an httpx request that does not go through a
    mock transport fails the test, except one to 127.0.0.1 (the fake `llama-server` these tests start)."""
    if not request.module.__name__.startswith(("test_builtin_embedding", "test_llama")):
        return
    import httpx

    real_sync, real_async = httpx.HTTPTransport.handle_request, httpx.AsyncHTTPTransport.handle_async_request

    def loopback_only(request_) -> None:
        if request_.url.host != "127.0.0.1":
            raise AssertionError("a built-in model test sent a request that did not go through a mock transport")

    def guarded_sync(self, request_):
        loopback_only(request_)
        return real_sync(self, request_)

    async def guarded_async(self, request_):
        loopback_only(request_)
        return await real_async(self, request_)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
