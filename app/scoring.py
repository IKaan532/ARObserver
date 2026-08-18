from app.config import (
    COMPRESSION_RULES,
    CONTENT_INTEGRITY_RULES,
    COOKIE_SECURITY_RULES,
    CSP_RULES,
    DNS_HYGIENE_RULES,
    HSTS_RECOMMENDED_MIN_MAX_AGE_SECONDS,
    HSTS_RULES,
    HTTPS_REDIRECT_RULES,
    INFO_LEAK_RULES,
    LETTER_GRADE_CEILING_INVALID_CERTIFICATE,
    LETTER_GRADE_CEILING_NO_FORWARD_SECRECY,
    LETTER_GRADE_CEILING_WEAK_CIPHER,
    LETTER_GRADE_CEILING_WEAK_TLS_VERSION,
    LETTER_GRADE_THRESHOLDS,
    SCORE_CATEGORIES,
    SECURITY_HEADER_RULES,
    TLS_CERTIFICATE_RULES,
    TLS_PROTOCOL_RULES,
)

GRADE_ORDER = ["A", "B", "C", "D", "F"]


def _grade_rank(grade: str) -> int:
    return GRADE_ORDER.index(grade)


def _parse_hsts(value: str) -> tuple[int | None, bool]:
    max_age = None
    include_subdomains = False
    for part in value.split(";"):
        part = part.strip()
        if part.lower().startswith("max-age="):
            try:
                max_age = int(part.split("=", 1)[1].strip())
            except ValueError:
                max_age = None
        elif part.lower() == "includesubdomains":
            include_subdomains = True
    return max_age, include_subdomains


def _parse_csp_directives(value: str) -> dict[str, list[str]]:
    directives = {}
    for part in value.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        directives[tokens[0].lower()] = tokens[1:]
    return directives


def _has_forward_secrecy(tls: dict | None) -> bool:
    if not tls:
        return True
    if tls.get("negotiated_protocol") == "TLSv1.3":
        return True
    cipher = (tls.get("cipher_name") or "").upper()
    return "ECDHE" in cipher or "DHE" in cipher


def _letter_grade_ceiling(tls: dict | None) -> tuple[str | None, str | None]:
    if not tls or not tls.get("applicable"):
        return None, None

    ceilings = []
    days_remaining = tls.get("days_remaining")
    if not tls.get("chain_valid") or (days_remaining is not None and days_remaining < 0):
        ceilings.append((LETTER_GRADE_CEILING_INVALID_CERTIFICATE, "sertifika süresi dolmuş veya zincir geçersiz"))
    if tls.get("weak_cipher"):
        ceilings.append((LETTER_GRADE_CEILING_WEAK_CIPHER, "zayıf şifre takımı kullanılıyor"))
    if tls.get("old_protocols_supported"):
        ceilings.append((LETTER_GRADE_CEILING_WEAK_TLS_VERSION, "TLS 1.0 veya 1.1 kabul ediliyor"))
    if not _has_forward_secrecy(tls):
        ceilings.append((LETTER_GRADE_CEILING_NO_FORWARD_SECRECY, "ileri gizlilik (forward secrecy) sağlanmıyor"))

    if not ceilings:
        return None, None
    return max(ceilings, key=lambda pair: _grade_rank(pair[0]))


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

        chain = tls.get("chain") or []
        leaf = chain[0] if chain else None
        if leaf:
            if leaf.get("signature_algorithm") == "sha1":
                rule = TLS_CERTIFICATE_RULES["weak_signature"]
                deductions.append(_deduction("weak_signature", "tls_certificate", rule["points"], rule["message"]))
            key_bits = leaf.get("key_bits")
            if leaf.get("key_type") == "RSA" and key_bits is not None and key_bits < 2048:
                rule = TLS_CERTIFICATE_RULES["weak_key"]
                deductions.append(
                    _deduction("weak_key", "tls_certificate", rule["points"], rule["message"].format(bits=key_bits))
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

    sts_info = security_headers.get("Strict-Transport-Security", {})
    sts_value = sts_info.get("value")
    if sts_info.get("present") and sts_value:
        max_age, include_subdomains = _parse_hsts(sts_value)
        if max_age is not None and max_age < HSTS_RECOMMENDED_MIN_MAX_AGE_SECONDS:
            rule = HSTS_RULES["short_max_age"]
            deductions.append(_deduction("hsts_short_max_age", "security_headers", rule["points"], rule["message"]))
        if not include_subdomains:
            rule = HSTS_RULES["missing_include_subdomains"]
            deductions.append(
                _deduction("hsts_missing_include_subdomains", "security_headers", rule["points"], rule["message"])
            )

    csp_info = security_headers.get("Content-Security-Policy", {})
    csp_value = csp_info.get("value")
    if csp_info.get("present") and csp_value:
        directives = _parse_csp_directives(csp_value)
        all_sources = [source for sources in directives.values() for source in sources]
        if "'unsafe-inline'" in all_sources:
            rule = CSP_RULES["unsafe_inline"]
            deductions.append(_deduction("csp_unsafe_inline", "security_headers", rule["points"], rule["message"]))
        if "'unsafe-eval'" in all_sources:
            rule = CSP_RULES["unsafe_eval"]
            deductions.append(_deduction("csp_unsafe_eval", "security_headers", rule["points"], rule["message"]))
        if "default-src" not in directives:
            rule = CSP_RULES["missing_default_src"]
            deductions.append(
                _deduction("csp_missing_default_src", "security_headers", rule["points"], rule["message"])
            )

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

    if reachability.get("network_issue"):
        return {
            "score": None,
            "letter_grade": None,
            "reasons": ["Yerel ağ sorunu nedeniyle bu kontrol değerlendirilmedi"],
            "breakdown": None,
            "critical_reason": "network_issue",
        }

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
    grade = letter_grade(score)

    ceiling_grade, ceiling_reason = _letter_grade_ceiling(results.get("tls"))
    if ceiling_grade is not None and _grade_rank(ceiling_grade) > _grade_rank(grade):
        reasons.append(f"Harf notu tavanı uygulandı ({ceiling_grade}): {ceiling_reason}")
        grade = ceiling_grade

    return {
        "score": score,
        "letter_grade": grade,
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
