import socket
from urllib.parse import urlparse

import dns.exception
import dns.resolver


def check_dns(url: str) -> dict:
    hostname = urlparse(url).hostname
    try:
        infos = socket.getaddrinfo(hostname, None)
        ip_addresses = sorted({info[4][0] for info in infos})
        return {"resolved": True, "hostname": hostname, "ip_addresses": ip_addresses, "error": None}
    except socket.gaierror as exc:
        return {"resolved": False, "hostname": hostname, "ip_addresses": [], "error": str(exc)}


def _txt_has_prefix(hostname: str, prefix: str, timeout: float) -> bool | None:
    try:
        answers = dns.resolver.resolve(hostname, "TXT", lifetime=timeout)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except dns.exception.DNSException:
        return None
    prefix_lower = prefix.lower()
    for rdata in answers:
        text = b"".join(rdata.strings).decode("utf-8", errors="ignore")
        if text.lower().startswith(prefix_lower):
            return True
    return False


def _has_caa(hostname: str, timeout: float) -> bool | None:
    try:
        answers = dns.resolver.resolve(hostname, "CAA", lifetime=timeout)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except dns.exception.DNSException:
        return None
    return len(answers) > 0


DNS_RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "NS"]


def _resolve_record_values(hostname: str, record_type: str, timeout: float) -> list[str]:
    try:
        answers = dns.resolver.resolve(hostname, record_type, lifetime=timeout)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException:
        return []
    return sorted({str(rdata).rstrip(".") for rdata in answers})


def check_dns_records(url: str, timeout: float = 5.0) -> dict:
    hostname = urlparse(url).hostname
    if not hostname:
        return {record_type.lower(): [] for record_type in DNS_RECORD_TYPES}
    return {
        record_type.lower(): _resolve_record_values(hostname, record_type, timeout)
        for record_type in DNS_RECORD_TYPES
    }


def check_dns_hygiene(url: str, timeout: float = 5.0) -> dict:
    hostname = urlparse(url).hostname
    if not hostname:
        return {"spf_present": None, "dmarc_present": None, "caa_present": None}
    return {
        "spf_present": _txt_has_prefix(hostname, "v=spf1", timeout),
        "dmarc_present": _txt_has_prefix(f"_dmarc.{hostname}", "v=DMARC1", timeout),
        "caa_present": _has_caa(hostname, timeout),
    }
