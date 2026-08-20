import asyncio
import logging

import dns.resolver
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SAFE_BROWSING_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
SAFE_BROWSING_THREAT_TYPES = [
    "MALWARE",
    "SOCIAL_ENGINEERING",
    "UNWANTED_SOFTWARE",
    "POTENTIALLY_HARMFUL_APPLICATION",
]


def _reversed_ip(ip: str) -> str | None:
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    return ".".join(reversed(parts))


def _is_policy_only_listing(query_name: str, resolver: dns.resolver.Resolver) -> bool | None:
    try:
        answers = resolver.resolve(query_name, "TXT")
    except Exception as exc:
        logger.warning("DNSBL TXT açıklaması alınamadı (%s): %s", query_name, exc)
        return None

    explanation = " ".join(b"".join(rdata.strings).decode("utf-8", errors="ignore") for rdata in answers)
    has_abuse_signal = any(code in explanation for code in ("SBL", "XBL", "DROP"))
    is_policy_only = "PBL" in explanation and not has_abuse_signal
    if is_policy_only:
        return True
    if has_abuse_signal:
        return False
    logger.warning("DNSBL açıklaması tanınamadı (%s): %s", query_name, explanation)
    return None


def check_dnsbl(ip: str, timeout: float = 5.0) -> bool | None:
    reversed_ip = _reversed_ip(ip)
    if reversed_ip is None:
        return None

    query_name = f"{reversed_ip}.{settings.dnsbl_zone}"
    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout
    try:
        resolver.resolve(query_name, "A")
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        return False
    except Exception as exc:
        logger.warning("DNSBL sorgusu başarısız (%s): %s", query_name, exc)
        return None

    policy_only = _is_policy_only_listing(query_name, resolver)
    if policy_only is None:
        return None
    return not policy_only


async def check_safe_browsing(url: str, timeout: float = 10.0) -> bool | None:
    if not settings.google_safe_browsing_api_key:
        return None

    payload = {
        "client": {"clientId": "arobserver", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": SAFE_BROWSING_THREAT_TYPES,
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    try:
        async with httpx.AsyncClient(headers={"User-Agent": settings.user_agent}) as client:
            response = await client.post(
                SAFE_BROWSING_URL,
                params={"key": settings.google_safe_browsing_api_key},
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Safe Browsing sorgusu başarısız (%s): %s", url, exc)
        return None

    return bool(data.get("matches"))


async def check_reputation(ip: str | None, url: str) -> dict:
    dnsbl_flagged = await asyncio.to_thread(check_dnsbl, ip) if ip else None
    safe_browsing_flagged = await check_safe_browsing(url)
    return {
        "dnsbl_flagged": dnsbl_flagged,
        "safe_browsing_flagged": safe_browsing_flagged,
        "safe_browsing_configured": bool(settings.google_safe_browsing_api_key),
    }
