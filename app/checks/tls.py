import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

CERT_DATE_FORMAT = "%b %d %H:%M:%S %Y %Z"


def _flatten_name(name_tuples) -> dict:
    parts = {}
    for rdn in name_tuples:
        for key, value in rdn:
            parts[key] = value
    return parts


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
            "error": str(exc),
        }

    subject = _flatten_name(cert.get("subject", ()))
    issuer = _flatten_name(cert.get("issuer", ()))
    not_before = datetime.strptime(cert["notBefore"], CERT_DATE_FORMAT).replace(tzinfo=timezone.utc)
    not_after = datetime.strptime(cert["notAfter"], CERT_DATE_FORMAT).replace(tzinfo=timezone.utc)
    days_remaining = (not_after - datetime.now(timezone.utc)).days

    return {
        "applicable": True,
        "valid": days_remaining >= 0,
        "chain_valid": True,
        "subject": subject.get("commonName"),
        "issuer": issuer.get("commonName") or issuer.get("organizationName"),
        "valid_from": not_before.isoformat(),
        "valid_to": not_after.isoformat(),
        "days_remaining": days_remaining,
        "error": None,
    }
