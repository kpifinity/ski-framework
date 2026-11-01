"""A throwaway RFC 3161 Time-Stamping Authority for the conformance rigs.

An HTTP server on loopback that answers ``application/timestamp-query`` with
``openssl ts -reply``, signing with a TSA certificate issued by a fresh CA.
It is what an air-gapped site runs in-boundary (an ``openssl ts`` front or a
hardware TSA), reduced to the protocol: the rigs use it to prove the runtime
obtains, stores and the auditor verifies real time-stamp tokens.
"""

from __future__ import annotations

import datetime
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

_CONFIG = """
[ tsa ]
default_tsa = tsa_config1
[ tsa_config1 ]
serial = {serial}
crypto_device = builtin
signer_digest = sha256
default_policy = 1.2.3.4.1
other_policies = 1.2.3.4.2
digests = sha256
accuracy = secs:1
ordering = no
tsa_name = no
ess_cert_id_chain = no
ess_cert_id_alg = sha256
"""


def _pki(directory: Path) -> tuple[Path, Path, Path]:
    """(ca.pem, tsa.pem, tsa.key): a CA and a TSA certificate with the critical timeStamping EKU."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)

    def name(cn: str) -> x509.Name:
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    def cert(subject: str, key: Any, signer: Any, *extensions: tuple[Any, bool]) -> x509.Certificate:
        builder = (
            x509.CertificateBuilder()
            .subject_name(name(subject))
            .issuer_name(name("conformance-tsa-ca"))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=2))
        )
        for extension, critical in extensions:
            builder = builder.add_extension(extension, critical=critical)
        return builder.sign(signer, hashes.SHA256())

    ca_key, tsa_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    ca = cert("conformance-tsa-ca", ca_key, ca_key, (x509.BasicConstraints(ca=True, path_length=None), True))
    tsa = cert(
        "conformance-tsa", tsa_key, ca_key, (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), True)
    )
    paths = directory / "ca.pem", directory / "tsa.pem", directory / "tsa.key"
    paths[0].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    paths[1].write_bytes(tsa.public_bytes(serialization.Encoding.PEM))
    paths[2].write_bytes(
        tsa_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return paths


@contextmanager
def running_tsa() -> Iterator[tuple[str, Path]]:
    """Serve a TSA on loopback; yields ``(url, ca_pem_path)``."""
    if shutil.which("openssl") is None:
        import pytest

        pytest.skip("openssl not available; the RFC 3161 stub TSA needs `openssl ts`.")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        ca, tsa_cert, tsa_key = _pki(directory)
        (directory / "serial").write_text("01\n")
        config = directory / "ts.cnf"
        config.write_text(_CONFIG.format(serial=directory / "serial"))

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                query, response = directory / "query.der", directory / "response.der"
                query.write_bytes(self.rfile.read(int(self.headers["Content-Length"])))
                subprocess.run(  # fixed argv, no shell
                    [
                        "openssl", "ts", "-reply", "-queryfile", str(query), "-signer", str(tsa_cert),
                        "-inkey", str(tsa_key), "-config", str(config), "-out", str(response),
                    ],
                    capture_output=True,
                    check=True,
                )  # fmt: skip
                reply = response.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/timestamp-reply")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *_: Any) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/tsa", ca
        finally:
            server.shutdown()
