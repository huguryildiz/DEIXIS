"""API keys kept in the system keychain and set from Settings (D29).

A key set in the shell or `.env` wins and cannot be changed from the app. Otherwise a key saved in Settings is stored
in the system keychain (macOS Keychain, Windows Credential Locker, Secret Service) under the service `DEIXIS`, and put
into the process environment, where connectors already read their keys at call time. Key values are never logged or
returned by the API.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from deixis.models.gemini import API_URL as GEMINI_API_URL
from deixis.models.gemini import error_message
from deixis.storage.db import now

SERVICE = "DEIXIS"
OPENAI_API_URL = "https://api.openai.com/v1"
DEEPSEEK_API_URL = "https://api.deepseek.com"


@dataclass(frozen=True)
class ManagedKey:
    env: str
    group: str  # 'model' or 'source'
    service: str
    testable: bool = False


MANAGED_KEYS = {k.env: k for k in (
    ManagedKey("GEMINI_API_KEY", "model", "gemini", testable=True),
    ManagedKey("OPENAI_API_KEY", "model", "openai", testable=True),
    ManagedKey("DEEPSEEK_API_KEY", "model", "deepseek", testable=True),
    ManagedKey("OPENALEX_API_KEY", "source", "openalex"),
    ManagedKey("S2_API_KEY", "source", "semantic_scholar"),
    ManagedKey("IEEE_API_KEY", "source", "ieee_xplore"),
    ManagedKey("SCOPUS_API_KEY", "source", "scopus"),
    ManagedKey("CORE_API_KEY", "source", "core"),
    ManagedKey("SERPAPI_API_KEY", "source", "serpapi"),
)}
_from_keychain: set[str] = set()


class KeySourceConflict(Exception):
    """The key is set in the shell or .env, which the app does not change."""


def keychain_name() -> str | None:
    backend = keyring.get_keyring()
    if backend.priority <= 0:  # the fail and null backends: no usable keychain
        return None
    return {"macOS": "macOS Keychain", "Windows": "Windows Credential Locker"}.get(
        type(backend).__module__.rsplit(".", 1)[-1], getattr(backend, "name", None) or type(backend).__name__)


def load_into_environment() -> None:
    """Fill unset key variables from the keychain; called after .env is read."""
    if keychain_name() is None:
        return
    for env in MANAGED_KEYS:
        if os.environ.get(env):
            continue
        try:
            value = keyring.get_password(SERVICE, env)
        except KeyringError:
            continue
        if value:
            os.environ[env] = value
            _from_keychain.add(env)


def status(env: str) -> dict[str, Any]:
    key = MANAGED_KEYS[env]
    configured = bool(os.environ.get(env))
    source = ("keychain" if env in _from_keychain else "environment") if configured else None
    return {"env": env, "group": key.group, "service": key.service, "configured": configured, "source": source,
            "testable": key.testable}


def save(env: str, value: str) -> None:
    if os.environ.get(env) and env not in _from_keychain:
        raise KeySourceConflict(f"{env} is set in .env or the shell; change or remove it there")
    keyring.set_password(SERVICE, env, value)
    os.environ[env] = value
    _from_keychain.add(env)


def delete(env: str) -> None:
    if os.environ.get(env) and env not in _from_keychain:
        raise KeySourceConflict(f"{env} is set in .env or the shell; change or remove it there")
    try:
        keyring.delete_password(SERVICE, env)
    except PasswordDeleteError:
        pass  # already absent from the keychain
    os.environ.pop(env, None)
    _from_keychain.discard(env)


async def test(client: httpx.AsyncClient, env: str, value: str) -> dict[str, str]:
    """One short request with the key: Gemini lists models; OpenAI embeds one word, which also shows missing credit."""
    try:
        if env == "GEMINI_API_KEY":
            response = await client.get(f"{GEMINI_API_URL}/models", params={"pageSize": 1},
                                        headers={"x-goog-api-key": value}, timeout=20)
        elif env == "DEEPSEEK_API_KEY":
            response = await client.get(f"{DEEPSEEK_API_URL}/models", headers={"Authorization": f"Bearer {value}"}, timeout=20)
        else:
            response = await client.post(f"{OPENAI_API_URL}/embeddings", json={"model": "text-embedding-3-small", "input": ["test"]},
                                         headers={"Authorization": f"Bearer {value}"}, timeout=20)
    except httpx.HTTPError as exc:
        return {"status": "failed", "detail": f"Could not reach the API: {type(exc).__name__}", "checked_at": now()}
    code = response.status_code
    if code == 200:
        return {"status": "ok", "detail": "The key works.", "checked_at": now()}
    if code in (400, 401, 403):  # the provider's own message can quote part of the key, so it is not passed on
        return {"status": "rejected", "detail": f"The API did not accept the key (HTTP {code}).", "checked_at": now()}
    # 429: Gemini quota or OpenAI insufficient_quota; the message says which.
    return {"status": "no_credit" if code == 429 else "failed", "detail": f"HTTP {code}: {error_message(response)}", "checked_at": now()}
