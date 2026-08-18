import http.cookies
import re

import httpx

from app.config import settings

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


def _parse_set_cookie(raw: str) -> dict | None:
    jar = http.cookies.SimpleCookie()
    try:
        jar.load(raw)
    except http.cookies.CookieError:
        return None
    for name, morsel in jar.items():
        return {
            "name": name,
            "secure": bool(morsel["secure"]),
            "http_only": bool(morsel["httponly"]),
            "same_site": morsel["samesite"] or None,
        }
    return None


async def check_headers(url: str, timeout: float = 10.0) -> dict:
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": settings.user_agent}
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return {"reachable": False, "security_headers": {}, "info_leak": {}, "cookies": [], "error": str(exc)}

    security_headers = {
        header: {"present": header in response.headers, "value": response.headers.get(header)}
        for header in SECURITY_HEADERS
    }
    info_leak = {header: _leak_entry(response.headers.get(header)) for header in LEAK_HEADERS}
    cookies = [
        parsed
        for raw in response.headers.get_list("set-cookie")
        if (parsed := _parse_set_cookie(raw)) is not None
    ]

    return {
        "reachable": True,
        "security_headers": security_headers,
        "info_leak": info_leak,
        "cookies": cookies,
        "error": None,
    }
