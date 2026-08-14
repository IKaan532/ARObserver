import hashlib
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import dsa, ec, rsa
from cryptography.x509.oid import NameOID

CERT_DATE_FORMAT = "%b %d %H:%M:%S %Y %Z"

WEAK_CIPHER_KEYWORDS = ("RC4", "DES", "MD5", "NULL", "EXPORT", "ADH", "AECDH")

OLD_PROTOCOL_VERSIONS = {
    "TLSv1": ssl.TLSVersion.TLSv1,
    "TLSv1.1": ssl.TLSVersion.TLSv1_1,
}


def _flatten_name(name_tuples) -> dict:
    parts = {}
    for rdn in name_tuples:
        for key, value in rdn:
            parts[key] = value
    return parts


def _common_name(name: x509.Name) -> str | None:
    attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return attrs[0].value if attrs else None


def _key_info(public_key) -> tuple[str, int | None]:
    if isinstance(public_key, rsa.RSAPublicKey):
        return "RSA", public_key.key_size
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        return f"EC ({public_key.curve.name})", public_key.key_size
    if isinstance(public_key, dsa.DSAPublicKey):
        return "DSA", public_key.key_size
    return type(public_key).__name__, None


def _parse_certificate(der: bytes) -> dict:
    cert = x509.load_der_x509_certificate(der)
    key_type, key_bits = _key_info(cert.public_key())
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
            x509.DNSName
        )
    except x509.ExtensionNotFound:
        san = []
    return {
        "subject_cn": _common_name(cert.subject),
        "issuer_cn": _common_name(cert.issuer),
        "valid_from": cert.not_valid_before_utc.isoformat(),
        "valid_to": cert.not_valid_after_utc.isoformat(),
        "serial_number": format(cert.serial_number, "X"),
        "signature_algorithm": cert.signature_hash_algorithm.name if cert.signature_hash_algorithm else None,
        "key_type": key_type,
        "key_bits": key_bits,
        "sha256_fingerprint": hashlib.sha256(der).hexdigest(),
        "san": san,
    }


def extract_certificate_chain(chain: list[bytes]) -> list[dict]:
    certificates = []
    for der in chain:
        try:
            certificates.append(_parse_certificate(der))
        except ValueError:
            continue
    return certificates


def _is_weak_cipher(cipher_name: str | None) -> bool:
    if not cipher_name:
        return False
    upper = cipher_name.upper()
    return any(keyword in upper for keyword in WEAK_CIPHER_KEYWORDS)


def _probe_protocol_version(hostname: str, port: int, version: ssl.TLSVersion, timeout: float) -> bool | None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        context.minimum_version = version
        context.maximum_version = version
        context.set_ciphers("ALL:@SECLEVEL=0")
    except (ssl.SSLError, ValueError):
        return None

    try:
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname):
                return True
    except ssl.SSLError:
        return False
    except OSError:
        return None


def check_tls_versions(hostname: str, port: int, timeout: float = 10.0) -> dict:
    old_protocol_supported = {
        label: _probe_protocol_version(hostname, port, version, timeout)
        for label, version in OLD_PROTOCOL_VERSIONS.items()
    }
    tls_1_3_supported = _probe_protocol_version(hostname, port, ssl.TLSVersion.TLSv1_3, timeout)
    return {
        "old_protocols": old_protocol_supported,
        "tls_1_3_supported": tls_1_3_supported,
    }


def check_tls(url: str, timeout: float = 10.0) -> dict:
    parsed = urlparse(url)
    hostname = parsed.hostname
    port = parsed.port or 443

    if parsed.scheme != "https":
        return {"applicable": False, "valid": None, "chain_valid": None, "error": "url is not https"}

    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                cipher_name, negotiated_protocol, _ = ssock.cipher() or (None, None, None)
                raw_chain = ssock.get_verified_chain()
    except OSError as exc:
        return {
            "applicable": True,
            "valid": False,
            "chain_valid": False,
            "subject": None,
            "issuer": None,
            "valid_from": None,
            "valid_to": None,
            "days_remaining": None,
            "negotiated_protocol": None,
            "cipher_name": None,
            "weak_cipher": None,
            "old_protocols_supported": None,
            "tls_1_3_supported": None,
            "chain": [],
            "error": str(exc),
        }

    chain = extract_certificate_chain(raw_chain)

    subject = _flatten_name(cert.get("subject", ()))
    issuer = _flatten_name(cert.get("issuer", ()))
    not_before = datetime.strptime(cert["notBefore"], CERT_DATE_FORMAT).replace(tzinfo=timezone.utc)
    not_after = datetime.strptime(cert["notAfter"], CERT_DATE_FORMAT).replace(tzinfo=timezone.utc)
    days_remaining = (not_after - datetime.now(timezone.utc)).days

    versions = check_tls_versions(hostname, port, timeout)
    old_protocols_supported = any(supported is True for supported in versions["old_protocols"].values())

    return {
        "applicable": True,
        "valid": days_remaining >= 0,
        "chain_valid": True,
        "subject": subject.get("commonName"),
        "issuer": issuer.get("commonName") or issuer.get("organizationName"),
        "valid_from": not_before.isoformat(),
        "valid_to": not_after.isoformat(),
        "days_remaining": days_remaining,
        "negotiated_protocol": negotiated_protocol,
        "cipher_name": cipher_name,
        "weak_cipher": _is_weak_cipher(cipher_name),
        "old_protocols_supported": old_protocols_supported,
        "old_protocols_detail": versions["old_protocols"],
        "tls_1_3_supported": versions["tls_1_3_supported"],
        "chain": chain,
        "error": None,
    }
