"""Certificates come from the operating system, not from a bundled list (pre-P10 F1).

httpx trusts the roots in `certifi`. A university or office network that inspects TLS signs with its own root, which
is in the system store (macOS Keychain, Windows certificate store, the Linux system store) and not in `certifi`, so
every request would fail with CERTIFICATE_VERIFY_FAILED. `use_system_certificates` makes `ssl` check certificates
against the system store; it runs once at start, before any HTTP client is built, and httpx then needs no `verify=`.

Precedence, with truststore 0.10 and httpx 0.28 (tests/rules/test_system_trust.py): the system store is always
trusted. A file named by SSL_CERT_FILE (or a folder in SSL_CERT_DIR) is added to it, not used instead of it; httpx
loads it next to the `certifi` list when a client has trust_env on. So a person who sets SSL_CERT_FILE keeps every
system root and gains the one in the file.

Python's setting does not reach child processes. uv takes UV_NATIVE_TLS and Node takes NODE_USE_SYSTEM_CA (see
child_env.UV_TLS and NODE_TLS); Codex is a native program with its own TLS and is left alone.
"""

from __future__ import annotations


def use_system_certificates() -> None:
    import truststore

    truststore.inject_into_ssl()
