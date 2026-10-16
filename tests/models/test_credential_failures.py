"""Why a key change fails, by cause, and what the response may say (B3, E14).

The keychains are fakes that raise what a locked, refusing or size-limited backend is known to raise: keyring's own error
types, the words backends use, and the Windows error number. They show how the app sorts those causes and what it
answers; a real macOS, Windows or Secret Service keychain was not asked.
"""

import os
import types

import httpx
import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import KeyringLocked, PasswordSetError

from deixis import credentials
from test_keychain_queue import (  # noqa: F401  (fixtures)
    KEY, V1, client, entry, no_keychain, no_redetection, no_shell_keys, only_while_a_test_uses_them)

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


@pytest.mark.parametrize("code,make", CAUSES)
def test_a_refused_keychain_change_names_its_cause_and_no_exception(code, make, client, caplog):
    keyring.set_keyring(Scripted(make()))
    credentials._found_cache = None
    with caplog.at_level("WARNING", logger="deixis.credentials"):
        saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
        removed = client.delete(f"/api/credentials/{KEY}")
    for response in (saved, removed):
        assert response.status_code == 503 and response.json() == {"code": code, "detail": credentials.FAILURES[code]}
        assert V1 not in response.text and not any(name in response.text for name in CLASS_NAMES)
    assert not os.environ.get(KEY) and entry(client)["configured"] is False
    assert type(make()).__name__ in caplog.text  # the class goes to the log, not to the response


def test_every_cause_code_has_a_sentence_and_one_the_page_words():
    assert set(credentials.FAILURES) == {c for c, _ in CAUSES} | {"file_write_failed"}


@pytest.mark.parametrize("error", [OSError(28, "No space left on device"), PermissionError(13, "Permission denied")])
def test_a_key_file_that_cannot_be_written_is_not_a_dotenv_or_an_exception(error, no_keychain, client, monkeypatch, caplog):  # noqa: F811
    def refuse():
        raise error

    with caplog.at_level("WARNING", logger="deixis.credentials"):
        with monkeypatch.context() as refusing:
            refusing.setattr(credentials, "_write_file_store", refuse)
            chosen = client.put("/api/credentials/file-store", json={"enabled": True})
        assert client.put("/api/credentials/file-store", json={"enabled": True}).status_code == 200
        with monkeypatch.context() as refusing:
            refusing.setattr(credentials, "_write_file_store", refuse)
            saved = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    for response in (chosen, saved):
        assert response.status_code == 503 and response.json() == {"code": "file_write_failed", "detail": credentials.FAILURES["file_write_failed"]}
        assert not any(name in response.text for name in CLASS_NAMES) and "space" not in response.text
    assert type(error).__name__ in caplog.text


def test_a_key_set_outside_the_app_is_refused_without_naming_the_variable(no_keychain, client, monkeypatch):  # noqa: F811
    monkeypatch.setenv(KEY, "shell-source-key-value")
    removed = client.delete(f"/api/credentials/{KEY}")
    assert removed.status_code == 409 and removed.json()["code"] == "shell_key" and KEY not in removed.text
    refused = client.put(f"/api/credentials/{KEY}", json={"value": V1})
    assert refused.status_code == 409 and refused.json()["code"] == "shell_key_stays" and KEY not in refused.text


def test_the_keychain_is_told_by_operating_system_not_by_backend_name(client, monkeypatch):
    mac, windows, other = (type("Backend", (), {"__module__": f"keyring.backends.{m}"})() for m in ("macOS", "Windows", "SecretService"))
    assert (credentials._kind(mac), credentials._kind(windows)) == ("macos", "windows")
    for platform, kind in (("darwin", "macos"), ("win32", "windows"), ("linux", "linux")):
        monkeypatch.setattr(credentials, "sys", types.SimpleNamespace(platform=platform))
        assert credentials._kind(other) == kind
    listed = client.get("/api/credentials").json()["keychain"]
    assert listed["available"] is True and listed["kind"] in {"macos", "windows", "linux"}
    keyring.set_keyring(fail.Keyring())
    credentials._found_cache = None
    assert client.get("/api/credentials").json()["keychain"]["kind"] is None


def test_the_page_words_every_cause_code_in_both_languages():
    """Runs the page's own label code under node: each code the backend can answer reads in English and Turkish, the keychain is
    named per system, and no sentence is left with a hole or a copy of the English line."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    codes = sorted(set(credentials.FAILURES) | {"keychain_not_responding", "keychain_busy", "file_store_damaged", "file_store_unavailable",
                                                "shell_key_stays", "shell_key", "not_testable", "key_not_set"})
    script = r"""
const fs = require('fs'), ts = require('typescript'), assert = require('assert');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText, file);
const labels = require('./src/labels.ts'), ocr = require('./src/ocr.ts'), i18n = require('./src/i18n.ts');
const codes = JSON.parse(process.argv[1]);
const seen = {};
for (const language of ['en', 'tr']) {
  i18n.setUiLanguage(language);
  seen[language] = {};
  for (const kind of ['macos', 'windows', 'linux', null]) {
    const keychain = labels.keychainLabel(kind);
    for (const code of codes) {
      const sentence = labels.credentialFailureText(code, keychain);
      assert(!sentence.includes('{') && !/DEIXIS_|_API_KEY|terminal that started|\.env/.test(sentence), code);
      if (language === 'tr') assert(sentence !== seen.en[kind + code], code + ' has no Turkish');
      seen[language][kind + code] = sentence;
    }
  }
  // A code this page does not know reads as a generic sentence in the language, never as backend text.
  const unknown = labels.credentialFailureText('something_new', 'x'), unknownInstall = labels.installReasonText('something_new', 'brew');
  assert(unknown && unknownInstall && !/something_new|FALLBACK/.test(unknown + unknownInstall));
  if (language === 'tr') { assert(unknown !== seen.en.unknown && unknownInstall !== seen.en.unknownInstall); }
  seen[language].unknown = unknown; seen[language].unknownInstall = unknownInstall;
  for (const code of ['uv_missing', 'manager_missing']) {
    const sentence = labels.installReasonText(code, 'brew');
    assert(sentence && !sentence.includes('{') && (code === 'uv_missing' || sentence.includes('brew')), code);
    if (language === 'tr') assert(sentence !== seen.en[code]);
    seen[language][code] = sentence;
  }
  for (const reason of ['tesseract_missing', 'tesseract_not_responding', 'tesseract_failed', 'tesseract_languages_missing']) {
    const sentence = ocr.ocrReasonText({ reason, missing_languages: ['tur'] });
    assert(sentence && !sentence.includes('{'), reason);
    if (language === 'tr') assert(sentence !== seen.en[reason], reason);
    seen[language][reason] = sentence;
  }
}
i18n.setUiLanguage('tr');
assert.deepStrictEqual(['macos', 'windows', 'linux'].map(labels.keychainLabel), ['Anahtar Zinciri', 'Kimlik Bilgisi Yöneticisi', 'sistem anahtarlığı']);
i18n.setUiLanguage('en');
assert.deepStrictEqual(['macos', 'windows', 'linux'].map(labels.keychainLabel), ['the Keychain', 'the Credential Manager', 'the system keyring']);
"""
    result = subprocess.run(["node", "-e", script, "--", __import__("json").dumps(codes)], cwd=root / "apps/web", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_a_key_that_cannot_be_tested_is_refused_by_code_without_naming_the_variable(client):
    assert client.post("/api/credentials/GEMINI_API_KEY/test").json()["code"] == "key_not_set"
    refused = client.post("/api/credentials/S2_API_KEY/test")  # no model list to test against
    for response in (client.post("/api/credentials/GEMINI_API_KEY/test"), refused, client.delete("/api/credentials/NOT_A_KEY")):
        assert response.status_code in (404, 422) and "_API_KEY" not in response.text and "NOT_A_KEY" not in response.text
    assert refused.json()["code"] in ("not_testable", "key_not_set")


def test_a_key_test_that_cannot_reach_the_api_does_not_name_the_exception(client, monkeypatch):
    class Down(httpx.AsyncClient):
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("SYNTHETIC unreachable")

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("SYNTHETIC unreachable")

    import asyncio
    result = asyncio.run(credentials.test(Down(), "OPENAI_API_KEY", "openai-source-good-key"))
    assert result["status"] == "failed" and "ConnectError" not in str(result) and "SYNTHETIC" not in str(result)


def test_the_first_run_text_names_the_built_in_model_only_where_it_is_offered():
    from pathlib import Path

    home = (Path(__file__).resolve().parents[2] / "apps/web/src/Home.tsx").read_text()
    assert "builtinOffered &&" in home and "unsupported_platform" in home
    assert "Semantic search also has a built-in model" not in home.split("{builtinOffered &&")[0].split("Not connected. Use a Codex")[1]
