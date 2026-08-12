from app.config import (
    COMPRESSION_RULES,
    CONTENT_INTEGRITY_RULES,
    COOKIE_SECURITY_RULES,
    DNS_HYGIENE_RULES,
    HTTPS_REDIRECT_RULES,
    INFO_LEAK_RULES,
    LETTER_GRADE_THRESHOLDS,
    SCORE_CATEGORIES,
    SECURITY_HEADER_RULES,
    TLS_CERTIFICATE_RULES,
    TLS_PROTOCOL_RULES,
)


def letter_grade(score: int) -> str:
    for threshold, grade in LETTER_GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _deduction(rule: str, category: str, points: int, message: str) -> dict:
    return {"rule": rule, "category": category, "points": points, "message": message}


def _finalize(category: str, deductions: list[dict]) -> dict:
    max_points = SCORE_CATEGORIES[category]["max_points"]
    lost = min(max_points, sum(item["points"] for item in deductions))
    return {"max": max_points, "earned": max_points - lost, "deductions": deductions}


def evaluate_tls_certificate(tls: dict) -> dict | None:
    if not tls:
        return None
    if not tls.get("applicable"):
        rule = TLS_CERTIFICATE_RULES["https_not_used"]
        return _finalize(
            "tls_certificate", [_deduction("https_not_used", "tls_certificate", rule["points"], rule["message"])]
        )

    deductions = []
    if not tls.get("chain_valid"):
        rule = TLS_CERTIFICATE_RULES["invalid_chain"]
        deductions.append(_deduction("invalid_chain", "tls_certificate", rule["points"], rule["message"]))
    else:
        days = tls.get("days_remaining")
        if days is not None and days < 0:
            rule = TLS_CERTIFICATE_RULES["expired"]
            deductions.append(_deduction("expired", "tls_certificate", rule["points"], rule["message"]))
        elif days is not None and days < 7:
            rule = TLS_CERTIFICATE_RULES["expiring_under_7_days"]
            deductions.append(
                _deduction("expiring_under_7_days", "tls_certificate", rule["points"], rule["message"].format(days=days))
            )
        elif days is not None and days < 14:
            rule = TLS_CERTIFICATE_RULES["expiring_under_14_days"]
            deductions.append(
                _deduction("expiring_under_14_days", "tls_certificate", rule["points"], rule["message"].format(days=days))
            )
        elif days is not None and days < 30:
            rule = TLS_CERTIFICATE_RULES["expiring_under_30_days"]
            deductions.append(
                _deduction("expiring_under_30_days", "tls_certificate", rule["points"], rule["message"].format(days=days))
            )

    return _finalize("tls_certificate", deductions)


def evaluate_security_headers(headers: dict) -> dict | None:
    if not headers or not headers.get("reachable", False):
        return None

    security_headers = headers.get("security_headers") or {}
    deductions = []
    for name, rule in SECURITY_HEADER_RULES.items():
        info = security_headers.get(name, {})
        if not info.get("present"):
            deductions.append(_deduction(f"missing_{name}", "security_headers", rule["points"], rule["message"]))

    return _finalize("security_headers", deductions)


def evaluate_tls_protocol(tls: dict) -> dict | None:
    if not tls:
        return None
    if not tls.get("applicable"):
        rule = TLS_PROTOCOL_RULES["https_not_used"]
        return _finalize(
            "tls_protocol", [_deduction("https_not_used", "tls_protocol", rule["points"], rule["message"])]
        )
    if tls.get("cipher_name") is None:
        return None

    deductions = []
    if tls.get("old_protocols_supported"):
        rule = TLS_PROTOCOL_RULES["weak_protocol"]
        deductions.append(_deduction("weak_protocol", "tls_protocol", rule["points"], rule["message"]))
    if tls.get("tls_1_3_supported") is False:
        rule = TLS_PROTOCOL_RULES["no_tls13"]
        deductions.append(_deduction("no_tls13", "tls_protocol", rule["points"], rule["message"]))
    if tls.get("weak_cipher"):
        rule = TLS_PROTOCOL_RULES["weak_cipher"]
        deductions.append(
            _deduction("weak_cipher", "tls_protocol", rule["points"], rule["message"].format(cipher=tls.get("cipher_name")))
        )

    return _finalize("tls_protocol", deductions)


def evaluate_https_redirect(redirect: dict) -> dict | None:
    if redirect is None:
        return None
    deductions = []
    if not redirect.get("error") and not redirect.get("redirects_to_https"):
        rule = HTTPS_REDIRECT_RULES["not_redirecting"]
        deductions.append(_deduction("not_redirecting", "https_redirect", rule["points"], rule["message"]))
    return _finalize("https_redirect", deductions)


def evaluate_cookie_security(headers: dict) -> dict | None:
    if not headers or not headers.get("reachable", False):
        return None

    cookies = headers.get("cookies") or []
    deductions = []
    if any(not cookie.get("secure") for cookie in cookies):
        rule = COOKIE_SECURITY_RULES["missing_secure"]
        deductions.append(_deduction("missing_secure", "cookie_security", rule["points"], rule["message"]))
    if any(not cookie.get("http_only") for cookie in cookies):
        rule = COOKIE_SECURITY_RULES["missing_httponly"]
        deductions.append(_deduction("missing_httponly", "cookie_security", rule["points"], rule["message"]))
    if any(cookie.get("same_site") in (None, "None") for cookie in cookies):
        rule = COOKIE_SECURITY_RULES["weak_samesite"]
        deductions.append(_deduction("weak_samesite", "cookie_security", rule["points"], rule["message"]))
    return _finalize("cookie_security", deductions)


def evaluate_dns_hygiene(dns_hygiene: dict) -> dict | None:
    if not dns_hygiene:
        return None
    fields = ("spf_present", "dmarc_present", "caa_present")
    if all(dns_hygiene.get(field) is None for field in fields):
        return None

    deductions = []
    if dns_hygiene.get("spf_present") is False:
        rule = DNS_HYGIENE_RULES["missing_spf"]
        deductions.append(_deduction("missing_spf", "dns_hygiene", rule["points"], rule["message"]))
    if dns_hygiene.get("dmarc_present") is False:
        rule = DNS_HYGIENE_RULES["missing_dmarc"]
        deductions.append(_deduction("missing_dmarc", "dns_hygiene", rule["points"], rule["message"]))
    if dns_hygiene.get("caa_present") is False:
        rule = DNS_HYGIENE_RULES["missing_caa"]
        deductions.append(_deduction("missing_caa", "dns_hygiene", rule["points"], rule["message"]))
    return _finalize("dns_hygiene", deductions)


def evaluate_content_integrity(content: dict) -> dict | None:
    if content is None:
        return None
    deductions = []
    if content.get("critical_changed"):
        rule = CONTENT_INTEGRITY_RULES["critical_change"]
        deductions.append(_deduction("critical_change", "content_integrity", rule["points"], rule["message"]))
    return _finalize("content_integrity", deductions)


def evaluate_info_leak(headers: dict) -> dict | None:
    if not headers or not headers.get("reachable", False):
        return None

    info_leak = headers.get("info_leak") or {}
    deductions = []
    for name, info in info_leak.items():
        if info.get("reveals_version"):
            rule = INFO_LEAK_RULES["version_leak"]
            deductions.append(
                _deduction("version_leak", "info_leak", rule["points"], rule["message"].format(header=name))
            )
            break

    return _finalize("info_leak", deductions)


def evaluate_compression(results: dict) -> dict | None:
    compression = results.get("compression")
    if compression is None:
        return None
    deductions = []
    if not compression.get("content_encoding"):
        rule = COMPRESSION_RULES["no_compression"]
        deductions.append(_deduction("no_compression", "compression", rule["points"], rule["message"]))
    return _finalize("compression", deductions)


CATEGORY_EVALUATORS = {
    "tls_certificate": lambda results: evaluate_tls_certificate(results.get("tls") or {}),
    "security_headers": lambda results: evaluate_security_headers(results.get("headers") or {}),
    "tls_protocol": lambda results: evaluate_tls_protocol(results.get("tls") or {}),
    "https_redirect": lambda results: evaluate_https_redirect(results.get("redirect")),
    "content_integrity": lambda results: evaluate_content_integrity(results.get("content")),
    "info_leak": lambda results: evaluate_info_leak(results.get("headers") or {}),
    "compression": evaluate_compression,
    "cookie_security": lambda results: evaluate_cookie_security(results.get("headers") or {}),
    "dns_hygiene": lambda results: evaluate_dns_hygiene(results.get("dns") or {}),
}


def calculate_score(results: dict) -> dict:
    reachability = results.get("reachability") or {}

    if not reachability.get("reachable"):
        suffix = " (zaman aşımı)" if reachability.get("timeout") else ""
        return {
            "score": 0,
            "letter_grade": "F",
            "reasons": [f"Hedefe erişilemedi{suffix}"],
            "breakdown": None,
            "critical_reason": "unreachable",
        }

    status_code = reachability.get("status_code") or 0
    if status_code >= 500:
        return {
            "score": 0,
            "letter_grade": "F",
            "reasons": [f"Sunucu hatası döndü (HTTP {status_code})"],
            "breakdown": None,
            "critical_reason": "server_error",
        }

    breakdown = {}
    reasons = []
    earned_total = 0
    max_total = 0
    for category, evaluator in CATEGORY_EVALUATORS.items():
        result = evaluator(results)
        breakdown[category] = result
        if result is None:
            continue
        earned_total += result["earned"]
        max_total += result["max"]
        reasons.extend(deduction["message"] for deduction in result["deductions"])

    score = round((earned_total / max_total) * 100) if max_total else 100
    score = max(0, min(100, score))

    return {
        "score": score,
        "letter_grade": letter_grade(score),
        "reasons": reasons,
        "breakdown": breakdown,
        "critical_reason": None,
    }


def recompute_score_breakdown(check: dict | None) -> dict | None:
    if not check or check.get("status_code") is None:
        return None

    timing = check.get("timing_result") or {}
    results = {
        "reachability": {"reachable": True, "status_code": check.get("status_code"), "timeout": False},
        "redirect": check.get("redirect_result"),
        "dns": check.get("dns_result"),
        "tls": check.get("tls_result"),
        "headers": check.get("headers_result"),
        "content": check.get("content_result"),
        "compression": (
            {"content_encoding": timing.get("content_encoding"), "body_size_bytes": timing.get("body_size_bytes")}
            if timing
            else None
        ),
    }
    return calculate_score(results)
