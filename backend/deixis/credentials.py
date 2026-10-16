"""API keys set from Settings (D29, D53).

A key saved in Settings wins over one set in the shell; removing it brings the shell key back. A shell key itself is
never changed or removed by the app. A key read from `.env` is moved into the keychain at
startup and its line deleted (D19); only when no keychain is available, or the move fails, is it replaced or removed in
that file. Otherwise a key saved in Settings is stored in the system keychain (macOS Keychain, Windows Credential Locker,
Secret Service) under the service `DEIXIS`. Either way it is put into the process environment, where connectors already
read their keys at call time. Key values are never logged or returned by the API.

Only a run from the repository reads or writes `.env` (A2). A packaged app never touches its install folder: it keeps keys
in the keychain (and, once A6 lands, in that item's session store when no keychain is available).
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from deixis.models.anthropic_api import API_URL as ANTHROPIC_API_URL, KEY_ENV as ANTHROPIC_KEY_ENV, headers as anthropic_headers
from deixis.models.gemini import API_URL as GEMINI_API_URL
from deixis.models.openai_compat import BY_KEY_ENV as COMPAT_BY_KEY_ENV
from deixis.paths import is_frozen
from deixis.storage.db import now
from deixis.domain.limits import service_error_kind, http_limit, retry_at

SERVICE = "DEIXIS"
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
    ManagedKey("GITHUB_TOKEN", "model", "copilot", testable=True),
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
dotenv_path: Path | None = None


class KeySourceConflict(Exception):
    """The key is set in the shell, which the app does not change."""


def keychain_name() -> str | None:
    backend = keyring.get_keyring()
    if backend.priority <= 0:  # the fail and null backends: no usable keychain
        return None
    return {"macOS": "macOS Keychain", "Windows": "Windows Credential Locker"}.get(
        type(backend).__module__.rsplit(".", 1)[-1], getattr(backend, "name", None) or type(backend).__name__)


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
            keyring.set_password(SERVICE, env, value)
            if keyring.get_password(SERVICE, env) != value:
                continue
            _rewrite_dotenv(env, None)
        except (KeyringError, OSError):
            continue
        _from_dotenv.discard(env)
        _from_keychain.add(env)


def load_into_environment() -> None:
    """Fill key variables from the keychain, over a shell value but not over `.env`; called after .env is read."""
    if keychain_name() is None:
        return
    for env in MANAGED_KEYS:
        if env in _from_dotenv or env in _from_keychain:
            continue
        try:
            value = keyring.get_password(SERVICE, env)
        except KeyringError:
            continue
        if value:
            if os.environ.get(env):
                _shell_values[env] = os.environ[env]
            os.environ[env] = value
            _from_keychain.add(env)


def status(env: str) -> dict[str, Any]:
    key = MANAGED_KEYS[env]
    value = os.environ.get(env) or ""
    configured = bool(value)
    source = ("keychain" if env in _from_keychain else "dotenv" if env in _from_dotenv else "environment") if configured else None
    # The last four characters let the user tell which key is saved; a short value is not shown at all.
    return {"env": env, "group": key.group, "service": key.service, "configured": configured, "source": source,
            "testable": key.testable, "shell_fallback": env in _shell_values, "last4": value[-4:] if len(value) >= 16 else None}


def save(env: str, value: str) -> None:
    source = status(env)["source"]
    if source == "dotenv":
        _rewrite_dotenv(env, value)
        os.environ[env] = value
        return
    keyring.set_password(SERVICE, env, value)
    if source == "environment":
        _shell_values[env] = os.environ[env]
    os.environ[env] = value
    _from_keychain.add(env)


def delete(env: str) -> None:
    source = status(env)["source"]
    if source == "environment":
        raise KeySourceConflict(f"{env} is set in the shell; change or remove it there")
    if source == "dotenv":
        _rewrite_dotenv(env, None)
        os.environ.pop(env, None)
        _from_dotenv.discard(env)
        return
    try:
        keyring.delete_password(SERVICE, env)
    except PasswordDeleteError:
        pass  # already absent from the keychain
    if env in _shell_values:
        os.environ[env] = _shell_values.pop(env)
    else:
        os.environ.pop(env, None)
    _from_keychain.discard(env)


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
    except httpx.HTTPError as exc:
        return {"status": "failed", "detail": f"Could not reach the API: {type(exc).__name__}", "checked_at": now(),
                "kind": service_error_kind(exc=exc), "http_status": None, "reset_at": None}
    code = response.status_code
    metadata = http_limit(response)
    fields = {"kind": metadata["error_kind"], "http_status": code, "reset_at": retry_at(metadata["retry_after"])}
    if code == 200:
        return {"status": "ok", "detail": "The key works.", "checked_at": now()}
    if code == 404 and env in COMPAT_BY_KEY_ENV and COMPAT_BY_KEY_ENV[env].static_models:
        return {"status": "ok", "detail": "Saved. This API lists no models, so the key is checked by the first step.", "checked_at": now()}
    if code == 403 and env == "SCOPUS_API_KEY":  # Elsevier knows the key (a wrong one gets 401) but this network has no access
        return {"status": "failed", "detail": "Elsevier knows the key, but Scopus gives no access from this network (HTTP 403).", "checked_at": now(), **fields}
    if code in (400, 401, 403):  # the provider's own message can quote part of the key, so it is not passed on
        return {"status": "rejected", "detail": f"The API did not accept the key (HTTP {code}).", "checked_at": now(), **fields}
    # 429: Gemini quota or OpenAI insufficient_quota; the message says which.
    return {"status": "no_credit" if code == 429 else "failed", "detail": f"API request failed (HTTP {code}).", "checked_at": now(), **fields}
