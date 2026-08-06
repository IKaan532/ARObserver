import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import FastAPI
from playwright.async_api import async_playwright
from pydantic import BaseModel

app = FastAPI()

DOM_TIMEOUT_MS = 20000
LOAD_GRACE_MS = 15000
NETWORK_IDLE_GRACE_MS = 8000
CONSOLE_LEVELS = {"error", "warning"}
SUBRESOURCE_TYPES = {"script", "stylesheet", "image"}
ALLOWED_SCHEMES = {"http", "https"}

CSP_INIT_SCRIPT = """
window.__cspViolations = [];
document.addEventListener('securitypolicyviolation', (e) => {
    window.__cspViolations.push({
        directive: e.violatedDirective,
        blocked_uri: e.blockedURI,
        source_file: e.sourceFile,
        line: e.lineNumber,
    });
});
"""

TIMING_SCRIPT = """() => {
    const nav = performance.getEntriesByType('navigation')[0];
    if (!nav) return {dcl: null, load: null};
    return {dcl: nav.domContentLoadedEventEnd || null, load: nav.loadEventEnd || null};
}"""

SRI_SCRIPT = """() => {
    const results = [];
    document.querySelectorAll('script[src], link[rel="stylesheet"][href]').forEach((el) => {
        const url = el.tagName === 'SCRIPT' ? el.src : el.href;
        results.push({
            tag: el.tagName.toLowerCase(),
            url,
            has_integrity: !!el.getAttribute('integrity'),
        });
    });
    return results;
}"""


class DeepCheckRequest(BaseModel):
    url: str


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _reject_reason_for_hostname(hostname: str) -> str | None:
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return "Alan adı çözümlenemedi."
    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return "Hedef özel/yerel bir ağ adresine çözümleniyor, derin kontrol engellendi."
    return None


def _same_site(host_a: str, host_b: str) -> bool:
    def normalize(host: str) -> str:
        return host[4:] if host.startswith("www.") else host

    a, b = normalize(host_a), normalize(host_b)
    if not a or not b:
        return False
    return a == b or a.endswith(f".{b}") or b.endswith(f".{a}")


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _navigation_reject_reason(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return "İzin verilmeyen protokol."
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return "Geçersiz url."
    return await asyncio.to_thread(_reject_reason_for_hostname, hostname)


@app.post("/deep-check")
async def deep_check(payload: DeepCheckRequest):
    target_host = _hostname(payload.url)
    if not target_host:
        return {"error": "Geçersiz url."}

    initial_reject_reason = await _navigation_reject_reason(payload.url)
    if initial_reject_reason:
        return {"error": initial_reject_reason}

    console_counter: dict[tuple, dict] = {}
    responses: list[dict] = []
    mixed_content: list[dict] = []
    request_count = {"value": 0}
    blocked_navigation_reason: dict[str, str | None] = {"value": None}

    def handle_console(message) -> None:
        if message.type not in CONSOLE_LEVELS:
            return
        location = message.location or {}
        source = location.get("url")
        key = (message.type, message.text)
        entry = console_counter.get(key)
        if entry is None:
            console_counter[key] = {"level": message.type, "message": message.text, "source": source, "count": 1}
        else:
            entry["count"] += 1

    def handle_request(req) -> None:
        request_count["value"] += 1
        if payload.url.startswith("https://") and req.url.startswith("http://"):
            mixed_content.append({"url": req.url, "resource_type": req.resource_type})

    def handle_response(resp) -> None:
        try:
            content_length = int(resp.headers.get("content-length", "0") or "0")
        except ValueError:
            content_length = 0
        responses.append(
            {
                "url": resp.url,
                "status": resp.status,
                "content_length": content_length,
                "resource_type": resp.request.resource_type,
            }
        )

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(args=["--no-sandbox"])
            context = await browser.new_context()
            await context.add_init_script(CSP_INIT_SCRIPT)
            page = await context.new_page()

            async def handle_route(route) -> None:
                request = route.request
                if request.frame == page.main_frame and request.is_navigation_request():
                    reason = await _navigation_reject_reason(request.url)
                    if reason:
                        blocked_navigation_reason["value"] = reason
                        await route.abort()
                        return
                await route.continue_()

            await page.route("**/*", handle_route)
            page.on("console", handle_console)
            page.on("request", handle_request)
            page.on("response", handle_response)

            await page.goto(payload.url, wait_until="domcontentloaded", timeout=DOM_TIMEOUT_MS)
            try:
                await page.wait_for_load_state("load", timeout=LOAD_GRACE_MS)
            except Exception:
                pass
            try:
                await page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_GRACE_MS)
            except Exception:
                pass

            timing = await page.evaluate(TIMING_SCRIPT)
            csp_violations = await page.evaluate("() => window.__cspViolations || []")
            sri_entries = await page.evaluate(SRI_SCRIPT)
            cookies_raw = await context.cookies()

            await browser.close()
    except Exception as exc:
        if blocked_navigation_reason["value"]:
            return {"error": blocked_navigation_reason["value"]}
        return {"error": f"Sayfa açılamadı veya zaman aşımına uğradı: {exc}"}

    own_console = []
    third_console = []
    for entry in console_counter.values():
        source = entry.get("source")
        source_host = _hostname(source) if source else ""
        if source_host and not _same_site(source_host, target_host):
            third_console.append(entry)
        else:
            own_console.append(entry)

    domain_stats: dict[str, dict] = {}
    for resp in responses:
        host = _hostname(resp["url"])
        if not host or _same_site(host, target_host):
            continue
        stats = domain_stats.setdefault(host, {"domain": host, "request_count": 0, "bytes": 0})
        stats["request_count"] += 1
        stats["bytes"] += resp["content_length"]

    own_failed = []
    third_failed = []
    for resp in responses:
        if resp["status"] < 400 or resp["resource_type"] not in SUBRESOURCE_TYPES:
            continue
        host = _hostname(resp["url"])
        entry = {"url": resp["url"], "status": resp["status"], "resource_type": resp["resource_type"]}
        if host and not _same_site(host, target_host):
            third_failed.append(entry)
        else:
            own_failed.append(entry)

    missing_sri = []
    present_sri_count = 0
    for entry in sri_entries:
        host = _hostname(entry["url"])
        if not host or _same_site(host, target_host):
            continue
        if entry["has_integrity"]:
            present_sri_count += 1
        else:
            missing_sri.append({"tag": entry["tag"], "url": entry["url"]})

    cookies = [
        {
            "name": cookie["name"],
            "domain": cookie["domain"],
            "secure": cookie.get("secure", False),
            "http_only": cookie.get("httpOnly", False),
            "same_site": cookie.get("sameSite"),
        }
        for cookie in cookies_raw
    ]

    return {
        "metrics": {
            "requests_total": request_count["value"],
            "bytes_total": sum(resp["content_length"] for resp in responses),
            "dom_content_loaded_ms": timing.get("dcl"),
            "load_ms": timing.get("load"),
        },
        "console": {"own_domain": own_console, "third_party": third_console},
        "mixed_content": mixed_content,
        "csp_violations": csp_violations,
        "third_party_domains": list(domain_stats.values()),
        "cookies": cookies,
        "sri": {"missing": missing_sri, "present_count": present_sri_count},
        "failed_subresources": {"own_domain": own_failed, "third_party": third_failed},
        "error": None,
    }
