import logging
from datetime import datetime, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
BOOTSTRAP_CACHE_HOURS = 24

_bootstrap_cache: dict[str, str] | None = None
_bootstrap_fetched_at: datetime | None = None


def _registrable_domain(host: str) -> str:
    labels = host.split(".")
    if len(labels) < 2:
        return host
    return ".".join(labels[-2:])


async def _get_rdap_bootstrap(client: httpx.AsyncClient) -> dict[str, str]:
    global _bootstrap_cache, _bootstrap_fetched_at
    if (
        _bootstrap_cache is not None
        and _bootstrap_fetched_at is not None
        and datetime.utcnow() - _bootstrap_fetched_at < timedelta(hours=BOOTSTRAP_CACHE_HOURS)
    ):
        return _bootstrap_cache

    response = await client.get(RDAP_BOOTSTRAP_URL, timeout=10)
    response.raise_for_status()
    data = response.json()

    lookup: dict[str, str] = {}
    for tlds, urls in data.get("services", []):
        if not urls:
            continue
        for tld in tlds:
            lookup[tld.lower()] = urls[0]

    _bootstrap_cache = lookup
    _bootstrap_fetched_at = datetime.utcnow()
    return lookup


def _extract_expiry(data: dict) -> datetime | None:
    for event in data.get("events", []):
        if event.get("eventAction") != "expiration":
            continue
        raw_date = event.get("eventDate")
        if not raw_date:
            return None
        try:
            return datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


async def check_domain_expiry(hostname: str, timeout: float = 10.0) -> dict:
    domain = _registrable_domain(hostname)
    tld = domain.rsplit(".", 1)[-1].lower()

    try:
        async with httpx.AsyncClient(headers={"User-Agent": settings.user_agent}) as client:
            bootstrap = await _get_rdap_bootstrap(client)
            base_url = bootstrap.get(tld)
            if base_url is None:
                return {"supported": False, "expiry_date": None}

            rdap_url = base_url.rstrip("/") + f"/domain/{domain}"
            response = await client.get(rdap_url, timeout=timeout)
            if response.status_code == 404:
                return {"supported": True, "expiry_date": None}
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("domain expiry check failed for %s: %s", domain, exc)
        return {"supported": None, "expiry_date": None}

    return {"supported": True, "expiry_date": _extract_expiry(data)}
