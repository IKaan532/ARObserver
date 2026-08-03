import re

import httpx

SECURITY_HEADERS = [
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
]

LEAK_HEADERS = ["Server", "X-Powered-By"]

VERSION_PATTERN = re.compile(r"\d")


def _leak_entry(value: str | None) -> dict:
    return {
        "present": value is not None,
        "value": value,
        "reveals_version": bool(value) and bool(VERSION_PATTERN.search(value)),
    }


async def check_headers(url: str, timeout: float = 10.0) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return {"reachable": False, "security_headers": {}, "info_leak": {}, "error": str(exc)}

    security_headers = {
        header: {"present": header in response.headers, "value": response.headers.get(header)}
        for header in SECURITY_HEADERS
    }
    info_leak = {header: _leak_entry(response.headers.get(header)) for header in LEAK_HEADERS}

    return {"reachable": True, "security_headers": security_headers, "info_leak": info_leak, "error": None}
