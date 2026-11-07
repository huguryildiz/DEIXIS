"""Make the self-signed code-signing identity the macOS build signs with (D171), once per build machine.

    uv run python packaging/mac_signing_identity.py

macOS ties a Keychain "Always Allow" to the app's signature. An ad-hoc signature is a hash of the binary, so every new build
was a stranger and the person was asked again for each saved key. A build signed by the same certificate keeps its
designated requirement (identifier plus certificate) across versions, so one "Always Allow" lasts. The certificate is
self-signed: Gatekeeper still treats the app as unsigned, which the README already says.

Makes an RSA key and a 10-year certificate with the code-signing extended key usage, imports both into the login keychain
with only /usr/bin/codesign allowed to use the key, and prints the identity. Does nothing when the identity exists. Keep a
copy of the .p12 it prints the path of if releases will be built on another Mac: a new certificate means one more question
per Mac for everyone who updates.
"""

from __future__ import annotations

import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

IDENTITY = "DEIXIS Self-Signed"


def exists() -> bool:
    found = subprocess.run(["security", "find-certificate", "-c", IDENTITY], capture_output=True)
    return found.returncode == 0


def main() -> int:
    if sys.platform != "darwin":
        print("Only for macOS.", file=sys.stderr)
        return 2
    if exists():
        print(f"{IDENTITY} is already in the keychain.")
        return 0
    folder = Path(tempfile.mkdtemp(prefix="deixis-signing-"))
    key, cert, p12 = folder / "key.pem", folder / "cert.pem", folder / "deixis-signing.p12"
    password = secrets.token_hex(12)
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
                    "-days", "3650", "-subj", f"/CN={IDENTITY}",
                    "-addext", "keyUsage=critical,digitalSignature",
                    "-addext", "extendedKeyUsage=critical,codeSigning",
                    "-addext", "basicConstraints=critical,CA:false"], check=True, capture_output=True)
    subprocess.run(["openssl", "pkcs12", "-export", "-legacy", "-inkey", str(key), "-in", str(cert), "-name", IDENTITY,
                    "-out", str(p12), "-passout", f"pass:{password}"], check=True, capture_output=True)
    key.unlink()
    subprocess.run(["security", "import", str(p12), "-k", str(Path.home() / "Library/Keychains/login.keychain-db"),
                    "-P", password, "-T", "/usr/bin/codesign"], check=True)
    (folder / "password.txt").write_text(password + "\n", encoding="utf-8")
    print(f"{IDENTITY} added. Backup: {p12} (password in {folder / 'password.txt'}); move both somewhere safe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
