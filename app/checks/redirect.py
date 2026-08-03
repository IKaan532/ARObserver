from urllib.parse import urlparse, urlunparse

import httpx


async def check_https_redirect(url: str, timeout: float = 10.0) -> dict:
    parsed = urlparse(url)
    http_url = urlunparse(parsed._replace(scheme="http"))
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(http_url)
        chain = [str(item.url) for item in response.history] + [str(response.url)]
        redirects_to_https = len(response.history) > 0 and str(response.url).startswith("https://")
        return {"checked_url": http_url, "redirects_to_https": redirects_to_https, "chain": chain, "error": None}
    except httpx.HTTPError as exc:
        return {"checked_url": http_url, "redirects_to_https": False, "chain": [], "error": str(exc)}
