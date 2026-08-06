import httpx

from app.config import KNOWN_TRACKER_DOMAINS, settings

DEEP_CHECK_TIMEOUT_SECONDS = 60.0
HEALTH_CHECK_TIMEOUT_SECONDS = 2.0

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


async def check_service_available() -> tuple[bool, str | None]:
    try:
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{settings.deepcheck_service_url}/health")
    except httpx.HTTPError:
        return False, "Derin kontrol servisine ulaşılamıyor."
    if response.status_code != 200:
        return False, f"Derin kontrol servisi hata döndü (HTTP {response.status_code})."
    return True, None


async def run_deep_check(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=DEEP_CHECK_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{settings.deepcheck_service_url}/deep-check", json={"url": url})
    except httpx.TimeoutException:
        return {"error": "Derin kontrol zaman aşımına uğradı (60 sn)."}
    except httpx.HTTPError as exc:
        return {"error": f"Derin kontrol servisine bağlanılamadı: {exc}"}

    if response.status_code != 200:
        return {"error": f"Derin kontrol servisi hata döndü (HTTP {response.status_code})."}

    result = response.json()
    if result.get("error"):
        return result

    for domain_entry in result.get("third_party_domains", []):
        domain_entry["is_tracker"] = _is_tracker(domain_entry["domain"])

    result["findings"] = _build_findings(result)
    return result


def _is_tracker(domain: str) -> bool:
    domain = domain.lower()
    return any(domain == tracker or domain.endswith(f".{tracker}") for tracker in KNOWN_TRACKER_DOMAINS)


def _build_findings(result: dict) -> list[dict]:
    findings = []

    mixed_content = result.get("mixed_content") or []
    if mixed_content:
        findings.append(
            {"severity": "high", "message": f"Karışık içerik: {len(mixed_content)} kaynak http üzerinden yükleniyor"}
        )

    csp_violations = result.get("csp_violations") or []
    if csp_violations:
        findings.append({"severity": "medium", "message": f"{len(csp_violations)} CSP ihlali tespit edildi"})

    insecure_cookies = [
        cookie
        for cookie in result.get("cookies") or []
        if not cookie.get("secure") or not cookie.get("http_only") or cookie.get("same_site") in (None, "None")
    ]
    if insecure_cookies:
        findings.append(
            {"severity": "medium", "message": f"{len(insecure_cookies)} çerezde güvenlik bayrağı eksik (Secure/HttpOnly/SameSite)"}
        )

    failed = result.get("failed_subresources") or {}
    own_failed = failed.get("own_domain") or []
    third_failed = failed.get("third_party") or []
    if own_failed:
        findings.append(
            {"severity": "medium", "message": f"Kendi alan adından {len(own_failed)} kaynak yüklenemedi (4xx/5xx)"}
        )
    if third_failed:
        findings.append(
            {"severity": "low", "message": f"Dış alan adlarından {len(third_failed)} kaynak yüklenemedi (4xx/5xx)"}
        )

    sri = result.get("sri") or {}
    missing_sri = sri.get("missing") or []
    if missing_sri:
        findings.append(
            {"severity": "low", "message": f"{len(missing_sri)} dış script/stylesheet'te bütünlük doğrulaması (SRI) yok"}
        )

    console = result.get("console") or {}
    own_console = console.get("own_domain") or []
    own_console_errors = sum(item.get("count", 1) for item in own_console if item.get("level") == "error")
    if own_console_errors:
        findings.append({"severity": "medium", "message": f"Kendi konsol {own_console_errors} hata mesajı üretiyor"})

    third_console = console.get("third_party") or []
    third_console_errors = sum(item.get("count", 1) for item in third_console if item.get("level") == "error")
    if third_console_errors:
        findings.append({"severity": "low", "message": f"Dış alan adlarından {third_console_errors} konsol hatası geliyor"})

    tracker_count = sum(1 for entry in result.get("third_party_domains") or [] if entry.get("is_tracker"))
    if tracker_count:
        findings.append({"severity": "low", "message": f"{tracker_count} bilinen izleyici/analitik alan adı tespit edildi"})

    findings.sort(key=lambda item: SEVERITY_ORDER.get(item["severity"], 99))
    return findings
