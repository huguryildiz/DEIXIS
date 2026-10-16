"""API keys set from Settings (D29, D53).

A key saved in Settings wins over one set in the shell; removing it brings the shell key back. A shell key itself is
never changed or removed by the app. A key read from `.env` is moved into the keychain at
startup and its line deleted (D19); only when no keychain is available, or the move fails, is it replaced or removed in
that file. Otherwise a key saved in Settings is stored in the system keychain (macOS Keychain, Windows Credential Locker,
Secret Service) under the service `DEIXIS`. Either way it is put into the process environment, where connectors already
read their keys at call time. Key values are never logged or returned by the API.

Only a run from the repository reads or writes `.env` (A2). A packaged app never touches its install folder: it keeps keys
in the keychain. With no keychain backend (Linux without Secret Service) a key lives in memory for this run only (A6), or in
an unencrypted file in the data folder when the person chose that.

Every call into the keychain runs on one worker thread, one at a time, with a time limit (E5): a keychain that never answers
holds up the keychain calls behind it, never the API or the start of the app.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import queue
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from deixis import key_verification
from deixis.models.anthropic_api import API_URL as ANTHROPIC_API_URL, KEY_ENV as ANTHROPIC_KEY_ENV, headers as anthropic_headers
from deixis.models.gemini import API_URL as GEMINI_API_URL
from deixis.models.openai_compat import BY_KEY_ENV as COMPAT_BY_KEY_ENV
from deixis.paths import is_frozen
from deixis.storage.db import now
from deixis.domain.limits import service_error_kind, http_limit, retry_at

SERVICE = "DEIXIS"
KEYCHAIN_TIMEOUT = 10.0  # seconds a keychain call may take before the app says the keychain is not responding (E5)
STARTUP_TIMEOUT = 20.0  # seconds the whole start-up read of saved keys may take
FILE_STORE = "keys-unencrypted.json"  # the opted-in file store in the data folder (A6)
OPENAI_API_URL = "https://api.openai.com/v1"
DEEPSEEK_API_URL = "https://api.deepseek.com"


@dataclass(frozen=True)
class ManagedKey:
    env: str
    group: str  # 'model', 'source' or 'equations'
    service: str
    testable: bool = False
    pair: bool = False  # saved, tested and removed only together on its own route; hidden from the generic key list


MANAGED_KEYS = {k.env: k for k in (
    ManagedKey("GEMINI_API_KEY", "model", "gemini", testable=True),
    ManagedKey("OPENAI_API_KEY", "model", "openai", testable=True),
    ManagedKey("DEEPSEEK_API_KEY", "model", "deepseek", testable=True),
    ManagedKey("DASHSCOPE_API_KEY", "model", "qwen", testable=True),
    ManagedKey("MOONSHOT_API_KEY", "model", "kimi", testable=True),
    ManagedKey("MISTRAL_API_KEY", "model", "mistral", testable=True),
    ManagedKey("XAI_API_KEY", "model", "grok", testable=True),
    ManagedKey("ZAI_API_KEY", "model", "glm", testable=True),
    ManagedKey("MODEL_API_KEY", "model", "muse_spark", testable=True),
    ManagedKey("ANTHROPIC_API_KEY", "model", "anthropic", testable=True),
    ManagedKey("OPENROUTER_API_KEY", "model", "openrouter", testable=True),
    ManagedKey("MIMO_API_KEY", "model", "mimo", testable=True),
    ManagedKey("OPENALEX_API_KEY", "source", "openalex", testable=True),
    ManagedKey("S2_API_KEY", "source", "semantic_scholar", testable=True),
    ManagedKey("NCBI_API_KEY", "source", "pubmed", testable=True),
    ManagedKey("IEEE_API_KEY", "source", "ieee_xplore", testable=True),
    ManagedKey("SCOPUS_API_KEY", "source", "scopus", testable=True),
    ManagedKey("CORE_API_KEY", "source", "core", testable=True),
    ManagedKey("SERPAPI_API_KEY", "source", "serpapi", testable=True),
    # The zotero.org pair is set on Settings' Zotero card; the library ID is not secret but is kept with its key (D19).
    ManagedKey("ZOTERO_API_KEY", "source", "zotero"),
    ManagedKey("ZOTERO_LIBRARY_ID", "source", "zotero"),
    # Kept in the keychain only; Settings shows no card for it (D19).
    ManagedKey("TYPESAFE_API_KEY", "source", "typesafe"),
    # Mathpix's app ID and key as one JSON item with a revision (D40), on `/api/credentials/mathpix`.
    ManagedKey("MATHPIX_CREDENTIALS", "equations", "mathpix", pair=True),
)}
_from_keychain: set[str] = set()
_from_dotenv: set[str] = set()
_shell_values: dict[str, str] = {}  # shell keys a keychain key replaced, restored when that key is removed
_broken: set[str] = set()  # keychain items skipped at startup because the value read is not a valid key (E2)
_unavailable: set[str] = set()  # keychain items not read at startup because the keychain did not answer; the item may be fine
dotenv_path: Path | None = None
_session: dict[str, str] = {}  # keys kept in memory when no keychain backend exists (A6); also what the file store holds
_data_dir: Path | None = None  # where the file store lives
_settling: dict[str, asyncio.Task[None]] = {}  # keys whose last keychain call timed out and is still unfinished (E5)


class KeySourceConflict(Exception):
    """The key is set in the shell, which the app does not change."""


class KeychainNotResponding(Exception):
    """The keychain did not answer in time; whether the change was made is not known yet."""


class KeychainBusy(Exception):
    """The previous change to this key has not finished, so a new one is refused."""


class FileStoreUnavailable(Exception):
    """A system keychain exists, so keys are kept there and a file store cannot be chosen."""


class _Worker:
    """One daemon thread takes every keychain call in turn: a call stuck inside the keychain blocks only the calls behind
    it, uses no thread pool, and does not keep the process from exiting."""

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[tuple[concurrent.futures.Future[Any], Any, tuple[Any, ...]]] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.running_since: float | None = None

    def submit(self, fn: Any, *args: Any) -> concurrent.futures.Future[Any]:
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="keychain", daemon=True)
                self._thread.start()
        self._queue.put((future, fn, args))
        return future

    def _run(self) -> None:
        while True:
            future, fn, args = self._queue.get()
            if not future.set_running_or_notify_cancel():  # cancelled while it waited: it never runs
                continue
            self.running_since = time.monotonic()
            try:
                future.set_result(fn(*args))
            except BaseException as exc:  # noqa: BLE001 - handed to the caller
                future.set_exception(exc)
            finally:
                self.running_since = None

    def stuck(self) -> bool:
        since = self.running_since
        return since is not None and time.monotonic() - since > KEYCHAIN_TIMEOUT


_worker = _Worker()


def _as_keyring_error(exc: BaseException) -> BaseException:
    return exc if isinstance(exc, (KeyringError, OSError, ValueError)) else KeyringError(type(exc).__name__)


def _call_sync(fn: Any, *args: Any) -> Any:
    """A keychain call from code with no event loop (start-up, tests): the same queue, the same time limit."""
    if _worker.stuck():
        raise KeychainNotResponding()
    future = _worker.submit(fn, *args)
    try:
        return future.result(timeout=KEYCHAIN_TIMEOUT)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise KeychainNotResponding() from exc
    except Exception as exc:  # noqa: BLE001
        raise _as_keyring_error(exc) from exc


async def _call(env: str, fn: Any, *args: Any) -> Any:
    """A keychain call from the API. On timeout the call may still finish later: until it has, a new change to the same key
    is refused, and when it finishes the keychain is read again so the app shows what it really holds (E5)."""
    future = _worker.submit(fn, *args)
    wrapped = asyncio.wrap_future(future)
    done, _ = await asyncio.wait({wrapped}, timeout=KEYCHAIN_TIMEOUT)
    if not done:
        if not future.cancel():  # already running inside the keychain: its outcome is unknown
            _settling[env] = asyncio.get_running_loop().create_task(_settle(env, wrapped))
        raise KeychainNotResponding()
    try:
        return wrapped.result()
    except Exception as exc:  # noqa: BLE001
        raise _as_keyring_error(exc) from exc


async def _settle(env: str, late: asyncio.Future[Any]) -> None:
    try:
        await asyncio.wait({late})
        if not late.cancelled():
            late.exception()  # a late failure is read here, not left unretrieved
        try:
            _adopt(env, await asyncio.wrap_future(_worker.submit(_store_get, env)))
        except Exception as exc:  # noqa: BLE001
            _note_unread(env, exc)
    finally:
        _settling.pop(env, None)


def keychain_name() -> str | None:
    backend = keyring.get_keyring()
    if backend.priority <= 0:  # the fail and null backends: no usable keychain
        return None
    return {"macOS": "macOS Keychain", "Windows": "Windows Credential Locker"}.get(
        type(backend).__module__.rsplit(".", 1)[-1], getattr(backend, "name", None) or type(backend).__name__)


def store_kind() -> str:
    """Where a saved key lives: the system 'keychain', the unencrypted 'file' the person chose, or this run's 'session' memory."""
    if keychain_name() is not None:
        return "keychain"
    return "file" if file_store_enabled() else "session"


def set_data_dir(path: Path) -> None:
    global _data_dir
    _data_dir = path


def file_store_enabled() -> bool:
    return _data_dir is not None and (_data_dir / FILE_STORE).is_file()


def _write_file_store() -> None:
    assert _data_dir is not None
    _data_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_data_dir, prefix=".keys.")  # created 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"keys": _session}, handle)
        os.chmod(tmp, 0o600)
        os.replace(tmp, _data_dir / FILE_STORE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def set_file_store(enabled: bool, data_dir: Path) -> None:
    """Choose to keep the session's keys in an unencrypted file in the data folder (0600), or stop. Only without a keychain."""
    if keychain_name() is not None:
        raise FileStoreUnavailable("A system keychain is available; keys are kept there")
    set_data_dir(data_dir)
    if enabled:
        _write_file_store()
    else:
        (data_dir / FILE_STORE).unlink(missing_ok=True)  # the keys stay in memory until DEIXIS closes


def _load_file_store() -> None:
    if not file_store_enabled():
        return
    try:
        data = json.loads((_data_dir / FILE_STORE).read_text(encoding="utf-8"))["keys"]  # type: ignore[operator]
    except (OSError, ValueError, KeyError, TypeError):
        return
    if isinstance(data, dict):
        _session.update({k: v for k, v in data.items() if k in MANAGED_KEYS and isinstance(v, str)})


def _store_get(env: str) -> str | None:
    return keyring.get_password(SERVICE, env) if keychain_name() is not None else _session.get(env)


def _store_set(env: str, value: str) -> None:
    if keychain_name() is not None:
        keyring.set_password(SERVICE, env, value)
        return
    _session[env] = value
    if file_store_enabled():
        _write_file_store()


def _store_delete(env: str) -> None:
    if keychain_name() is not None:
        try:
            keyring.delete_password(SERVICE, env)
        except PasswordDeleteError:
            pass  # already absent from the keychain
        return
    _session.pop(env, None)
    if file_store_enabled():
        _write_file_store()


async def _io(env: str, fn: Any, *args: Any) -> Any:
    """A store call from the API: the keychain goes through the queue, memory and the file are fast and run here."""
    return await _call(env, fn, *args) if keychain_name() is not None else fn(*args)


def _io_sync(fn: Any, *args: Any) -> Any:
    return _call_sync(fn, *args) if keychain_name() is not None else fn(*args)


def _note_unread(env: str, exc: BaseException) -> None:
    """A stored item that could not be read: damaged bytes make it broken, anything else means the keychain did not answer."""
    (_broken if isinstance(exc, ValueError) else _unavailable).add(env)


def _adopt(env: str, value: str | None) -> None:
    """Make the process environment match what the store holds for this key."""
    _broken.discard(env)
    _unavailable.discard(env)
    if value:
        if not _stored_value_ok(MANAGED_KEYS[env], value):
            _broken.add(env)
            return
        if os.environ.get(env) and env not in _from_keychain:
            _shell_values[env] = os.environ[env]
        os.environ[env] = value
        _from_keychain.add(env)
    elif env in _from_keychain:
        _from_keychain.discard(env)
        if env in _shell_values:
            os.environ[env] = _shell_values.pop(env)
        else:
            os.environ.pop(env, None)


def mark_dotenv(names: set[str], path: Path) -> None:
    """Remember which managed keys came from `.env`, so they are changed in that file."""
    global dotenv_path
    dotenv_path = path
    _from_dotenv.clear()
    _from_dotenv.update(names & MANAGED_KEYS.keys())


def _rewrite_dotenv(env: str, value: str | None) -> None:
    """Replace the key's line in `.env` (or drop it when value is None), keeping every other line and the file mode."""
    if is_frozen():
        raise RuntimeError("a packaged app does not write .env")
    assert dotenv_path is not None
    pattern = re.compile(rf"^\s*{re.escape(env)}\s*=")
    lines = dotenv_path.read_text(encoding="utf-8").splitlines(keepends=True) if dotenv_path.exists() else []
    kept, replaced = [], False
    for line in lines:
        if pattern.match(line):
            if value is not None and not replaced:
                kept.append(f"{env}={value}\n")
                replaced = True
            continue
        kept.append(line)
    if value is not None and not replaced:
        if kept and not kept[-1].endswith("\n"):
            kept[-1] += "\n"
        kept.append(f"{env}={value}\n")
    mode = dotenv_path.stat().st_mode & 0o777 if dotenv_path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=dotenv_path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(kept)
        os.chmod(tmp, mode)
        os.replace(tmp, dotenv_path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def move_dotenv_keys_to_keychain() -> None:
    """Move managed keys read from `.env` into the keychain and delete their lines (D19). A key is deleted from `.env`
    only after the keychain returns the same value; on any failure it stays in `.env`, still in use."""
    if keychain_name() is None:
        return
    for env in sorted(_from_dotenv):
        value = os.environ.get(env)
        if not value:
            continue
        try:
            _call_sync(keyring.set_password, SERVICE, env, value)
            if _call_sync(keyring.get_password, SERVICE, env) != value:
                continue
            _rewrite_dotenv(env, None)
        except (KeyringError, OSError, ValueError, KeychainNotResponding):
            continue
        _from_dotenv.discard(env)
        _from_keychain.add(env)


def _stored_value_ok(key: ManagedKey, value: str) -> bool:
    """Whether a value read from the keychain is one this app would have saved: a key of printable ASCII, or for a pair
    the JSON item whose secrets are such keys."""
    if not key.pair:
        return key_verification.is_valid_key(value)
    try:
        data = json.loads(value)
    except ValueError:
        return False
    return (isinstance(data, dict) and all(isinstance(data.get(k), str) and key_verification.is_valid_key(data[k])
                                           for k in ("app_id", "app_key", "revision")))


def load_into_environment() -> None:
    """Fill key variables from the keychain (or, with none, the session store and the file the person chose), over a shell
    value but not over `.env`; called after .env is read. An item that cannot be read or is not a valid key is skipped, never
    put into the environment, and shown as broken (E2). A keychain that does not answer in time leaves the keys it holds
    unread and shown as unavailable; the app starts without them (E5)."""
    _broken.clear()
    _unavailable.clear()
    todo = [env for env in MANAGED_KEYS if env not in _from_dotenv and env not in _from_keychain]
    if keychain_name() is None:
        _load_file_store()
        for env in todo:
            if value := _session.get(env):
                _adopt(env, value)
        return
    reads = {env: _worker.submit(_store_get, env) for env in todo}  # all queued at once, read against one deadline
    deadline = time.monotonic() + STARTUP_TIMEOUT
    for env, read in reads.items():
        try:
            value = read.result(timeout=max(0.0, deadline - time.monotonic()))
        except concurrent.futures.TimeoutError:
            read.cancel()
            _unavailable.add(env)
            continue
        except Exception as exc:  # noqa: BLE001 - a locked or unreachable keychain, in whatever way the backend reports it
            _note_unread(env, exc)
            continue
        if value:
            _adopt(env, value)


def status(env: str) -> dict[str, Any]:
    key = MANAGED_KEYS[env]
    value = os.environ.get(env) or ""
    configured = bool(value)
    source = (store_kind() if env in _from_keychain else "dotenv" if env in _from_dotenv else "environment") if configured else None
    # The last four characters let the user tell which key is saved; a short value is not shown at all.
    return {"env": env, "group": key.group, "service": key.service, "configured": configured, "source": source,
            "testable": key.testable, "shell_fallback": env in _shell_values, "last4": value[-4:] if len(value) >= 16 else None,
            # 'verified', 'pending' (saved, no request showed it works) or 'rejected'; None when not checked in this run.
            "verification": key_verification.state_of(value) if configured else None,
            "broken": (env in _broken and not configured) or (configured and not key.pair and not key_verification.is_valid_key(value)),
            # The keychain did not answer, so the saved key was not used this time; it is not known to be bad.
            "keychain_unavailable": env in _unavailable and not configured,
            # The last change to this key got no answer from the keychain yet; the key shows its real state when it does (E5).
            "keychain_pending": env in _settling}


def _prepare_save(env: str, value: str) -> str | None:
    if not MANAGED_KEYS[env].pair and not key_verification.is_valid_key(value):
        raise ValueError("not a valid key")  # the routes refuse these first; this keeps one out of the environment for good
    if env in _settling:
        raise KeychainBusy()
    return status(env)["source"]


def _save_dotenv(env: str, value: str) -> None:
    _rewrite_dotenv(env, value)
    os.environ[env] = value
    _broken.discard(env)
    _unavailable.discard(env)


def _finish_save(env: str, value: str, source: str | None) -> None:
    if source == "environment":
        _shell_values[env] = os.environ[env]
    os.environ[env] = value
    _from_keychain.add(env)
    _broken.discard(env)
    _unavailable.discard(env)


def save(env: str, value: str) -> None:
    source = _prepare_save(env, value)
    if source == "dotenv":
        return _save_dotenv(env, value)
    _io_sync(_store_set, env, value)
    _finish_save(env, value, source)


async def save_async(env: str, value: str) -> None:
    """`save` for the API: the keychain call goes through the queue with a time limit (E5)."""
    source = _prepare_save(env, value)
    if source == "dotenv":
        return _save_dotenv(env, value)
    await _io(env, _store_set, env, value)
    _finish_save(env, value, source)


def _prepare_delete(env: str) -> str | None:
    if env in _settling:
        raise KeychainBusy()
    source = status(env)["source"]
    _broken.discard(env)
    if source == "environment":
        raise KeySourceConflict(f"{env} is set in the shell; change or remove it there")
    if source == "dotenv":
        _rewrite_dotenv(env, None)
        os.environ.pop(env, None)
        _from_dotenv.discard(env)
    return source


def _finish_delete(env: str) -> None:
    if env in _shell_values:
        os.environ[env] = _shell_values.pop(env)
    else:
        os.environ.pop(env, None)
    _from_keychain.discard(env)


def delete(env: str) -> None:
    if _prepare_delete(env) == "dotenv":
        return
    _io_sync(_store_delete, env)
    _finish_delete(env)


async def delete_async(env: str) -> None:
    if _prepare_delete(env) == "dotenv":
        return
    await _io(env, _store_delete, env)
    _finish_delete(env)


# One short request per scholarly source, sent the way its adapter sends the key. Each source answers a made-up key
# with 400/401/403 (checked 15 Oct 2026), so 200 means the key itself works, not only the keyless route. SerpApi's
# account page costs no search; the others ask for one record.
def _source_request(env: str, value: str) -> tuple[str, dict[str, Any], dict[str, str]] | None:
    return {
        "OPENALEX_API_KEY": ("https://api.openalex.org/works", {"per_page": 1, "select": "id"}, {"Authorization": f"Bearer {value}"}),
        "S2_API_KEY": ("https://api.semanticscholar.org/graph/v1/paper/search", {"query": "test", "limit": 1, "fields": "title"}, {"x-api-key": value}),
        "NCBI_API_KEY": ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi", {"db": "pubmed", "retmode": "json", "api_key": value}, {}),
        "IEEE_API_KEY": ("https://ieeexploreapi.ieee.org/api/v1/search/articles", {"querytext": "test", "max_records": 1, "format": "json", "apikey": value}, {}),
        "SCOPUS_API_KEY": ("https://api.elsevier.com/content/search/scopus", {"query": "TITLE(test)", "count": 1}, {"X-ELS-APIKey": value, "Accept": "application/json"}),
        "CORE_API_KEY": ("https://api.core.ac.uk/v3/search/works/", {"q": "test", "limit": 1}, {"Authorization": f"Bearer {value}"}),
        "SERPAPI_API_KEY": ("https://serpapi.com/account.json", {"api_key": value}, {}),
    }.get(env)


async def test(client: httpx.AsyncClient, env: str, value: str) -> dict[str, Any]:
    """One short request with the key: a scholarly source asks for one record (SerpApi: its account page); Gemini, DeepSeek, Anthropic and the OpenAI-compatible connections list models (OpenRouter reads its key's limits); OpenAI embeds one word, which also shows missing credit."""
    if not key_verification.is_valid_key(value):  # a header cannot carry it; nothing is sent
        return {"status": "rejected", "verification": "rejected", "detail": "The saved key is not a valid key. Enter it again.",
                "checked_at": now(), "kind": "auth_failed", "http_status": None, "reset_at": None}
    source = _source_request(env, value)
    try:
        if source:
            url, params, headers = source
            response = await client.get(url, params=params, headers=headers, timeout=20)
        elif env == "GEMINI_API_KEY":
            response = await client.get(f"{GEMINI_API_URL}/models", params={"pageSize": 1},
                                        headers={"x-goog-api-key": value}, timeout=20)
        elif env == "DEEPSEEK_API_KEY":
            response = await client.get(f"{DEEPSEEK_API_URL}/models", headers={"Authorization": f"Bearer {value}"}, timeout=20)
        elif env == ANTHROPIC_KEY_ENV:
            response = await client.get(f"{ANTHROPIC_API_URL}/models", params={"limit": 1}, headers=anthropic_headers(value), timeout=20)
        elif env in COMPAT_BY_KEY_ENV:  # OpenRouter's model list is public, so its key is checked where it is read
            spec = COMPAT_BY_KEY_ENV[env]
            response = await client.get(spec.key_url or spec.list_url, headers={"Authorization": f"Bearer {value}"}, timeout=20)
        else:
            response = await client.post(f"{OPENAI_API_URL}/embeddings", json={"model": "text-embedding-3-small", "input": ["test"]},
                                         headers={"Authorization": f"Bearer {value}"}, timeout=20)
    except (httpx.HTTPError, UnicodeEncodeError) as exc:
        return {"status": "failed", "verification": "pending", "detail": f"Could not reach the API: {type(exc).__name__}", "checked_at": now(),
                "kind": service_error_kind(exc=exc), "http_status": None, "reset_at": None}
    code = response.status_code
    metadata = http_limit(response)
    fields = {"kind": metadata["error_kind"], "http_status": code, "reset_at": retry_at(metadata["retry_after"])}
    if code == 200:
        return {"status": "ok", "verification": "verified", "detail": "The key works.", "checked_at": now()}
    if code == 404 and env in COMPAT_BY_KEY_ENV and COMPAT_BY_KEY_ENV[env].static_models:
        return {"status": "unverified", "verification": "pending", "checked_at": now(), "http_status": code, "kind": "unknown",
                "reset_at": None, "detail": "Saved, not verified. This API lists no models, so the key is checked by the first step."}
    # The only 403 that is not a refusal: Elsevier knows the key (a wrong one gets 401), the network just has no access.
    if code == 403 and env == "SCOPUS_API_KEY":  # Elsevier knows the key (a wrong one gets 401) but this network has no access
        return {"status": "failed", "verification": "pending", "detail": "Elsevier knows the key, but Scopus gives no access from this network (HTTP 403).", "checked_at": now(), **fields}
    if code in (400, 401, 403):  # the provider's own message can quote part of the key, so it is not passed on
        return {"status": "rejected", "verification": "rejected", "detail": f"The API did not accept the key (HTTP {code}).", "checked_at": now(), **fields}
    # 429: Gemini quota or OpenAI insufficient_quota; the message says which.
    return {"status": "no_credit" if code == 429 else "failed", "verification": "pending", "detail": f"API request failed (HTTP {code}).", "checked_at": now(), **fields}
