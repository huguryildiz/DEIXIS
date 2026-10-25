"""Certificates from the operating system's store (pre-P10 F1).

A local TLS server presents a self-signed certificate that `certifi` does not list, as a network that inspects TLS would.
Each case runs in a fresh Python so the global `ssl` change of `truststore` does not leak into other tests. The "system
store" of the cases that need a store is a stand-in function in place of the operating system's verifier; the case with
SSL_CERT_FILE uses truststore's real verifier. Passing shows the wiring and the reason code, not a real corporate proxy."""

import datetime
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from deixis.domain.limits import certificate_failure, error_name, service_error_kind

BACKEND = str(Path(__file__).resolve().parents[2])


def certificate(folder: Path, name: str, host: str = "localhost") -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"SYNTHETIC test root {name}")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)  # macOS insists
            .sign(key, hashes.SHA256()))
    pem, key_pem = folder / f"{name}.pem", folder / f"{name}.key"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return pem, key_pem


SCRIPT = textwrap.dedent('''
    import asyncio, json, os, socket, ssl, sys, threading
    sys.path.insert(0, {backend!r})
    mode = json.loads(sys.argv[1])
    cert, key = mode["server_cert"], mode["server_key"]
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)  # made first: truststore would replace the class
    server_context.load_cert_chain(cert, key)
    if mode["inject"]:
        from deixis.system_trust import use_system_certificates
        use_system_certificates()
    if mode["store"] is not None:  # a stand-in for the operating system's verifier
        import truststore._api as api
        trusted = [ssl.PEM_cert_to_DER_cert(open(p).read()) for p in mode["store"]]
        def verify(context, chain, server_hostname=None):
            if not chain or chain[0] not in trusted:
                raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unknown root")
        api._verify_peercerts_impl = verify
    import httpx
    from deixis.domain.limits import error_name, service_error_kind

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]

    def serve():
        while True:
            try:
                connection, _ = listener.accept()
                with server_context.wrap_socket(connection, server_side=True) as tls:
                    tls.recv(65536)
                    tls.sendall(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\n\\r\\nok")
            except Exception:
                pass
    threading.Thread(target=serve, daemon=True).start()

    async def main():
        async with httpx.AsyncClient(timeout=10) as client:
            context = type(client._transport._pool._ssl_context).__module__
            try:
                response = await client.get(f"https://localhost:{{port}}/")
                return dict(ok=response.text == "ok", context=context)
            except httpx.ConnectError as exc:
                return dict(ok=False, kind=service_error_kind(exc=exc), name=error_name(exc), context=context)
    print(json.dumps(asyncio.run(main())))
''')


def run_case(tmp_path, *, inject, store=None, env_file=None, server=None):
    pem, key = server or certificate(tmp_path, "server")
    mode = {"inject": inject, "store": None if store is None else [str(p) for p in store], "server_cert": str(pem), "server_key": str(key)}
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONPATH": BACKEND}
    if env_file:
        env["SSL_CERT_FILE"] = str(env_file)
    done = subprocess.run([sys.executable, "-c", SCRIPT.format(backend=BACKEND), json.dumps(mode)], env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_with_the_system_store_the_same_server_is_trusted(tmp_path):
    server = certificate(tmp_path, "server")
    result = run_case(tmp_path, inject=True, store=[server[0]], server=server)
    assert result["ok"] is True and result["context"].startswith("truststore")  # httpx built a truststore context


def test_a_certificate_the_system_store_does_not_have_is_refused_with_the_reason(tmp_path):
    other, _ = certificate(tmp_path, "other")
    result = run_case(tmp_path, inject=True, store=[other])
    assert result["ok"] is False and result["kind"] == "certificate"


def test_the_main_entry_point_turns_the_system_store_on_before_anything_else():
    source = (Path(BACKEND) / "deixis" / "__main__.py").read_text()
    assert source.index("use_system_certificates()") < source.index("settings = load_settings()")


# ---- the reason code ------------------------------------------------------------------------------

def test_a_refused_certificate_is_told_apart_from_a_server_that_cannot_be_reached():
    import httpx
    import ssl

    refused = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    refused.__cause__ = ssl.SSLCertVerificationError(1, "certificate verify failed")
    unreachable = httpx.ConnectError("[Errno 61] Connection refused")
    assert (certificate_failure(refused), certificate_failure(unreachable)) == (True, False)
    assert (service_error_kind(exc=refused), service_error_kind(exc=unreachable)) == ("certificate", "network")
    assert (error_name(refused), error_name(unreachable)) == ("CertificateError", "ConnectError")
    # What the call sites store is read back the same way, with or without the exception.
    assert service_error_kind("failed", text="CertificateError before_send") == "certificate"
    assert service_error_kind("failed", text="ConnectError before_send") == "network"
    assert service_error_kind(text="[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed") == "certificate"


