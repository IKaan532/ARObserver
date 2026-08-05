from app.config import CERT_EXPIRY_SCORE_WARN_DAYS, LETTER_GRADE_THRESHOLDS, SCORE_WEIGHTS


def letter_grade(score: int) -> str:
    for threshold, grade in LETTER_GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def calculate_score(results: dict) -> dict:
    score = 100
    reasons = []

    reachability = results.get("reachability") or {}
    redirect = results.get("redirect") or {}
    dns = results.get("dns") or {}
    tls = results.get("tls") or {}
    headers = results.get("headers") or {}

    if not reachability.get("reachable"):
        score -= SCORE_WEIGHTS["unreachable"]
        suffix = " (zaman aşımı)" if reachability.get("timeout") else ""
        reasons.append(f"Hedefe erişilemedi{suffix}")
    else:
        status_code = reachability.get("status_code") or 0
        if status_code >= 500:
            score -= SCORE_WEIGHTS["server_error"]
            reasons.append(f"Sunucu hatası döndü (HTTP {status_code})")
        elif status_code >= 400:
            score -= SCORE_WEIGHTS["client_error"]
            reasons.append(f"İstemci hatası döndü (HTTP {status_code})")

    if not dns.get("resolved"):
        score -= SCORE_WEIGHTS["dns_unresolved"]
        reasons.append("Alan adı çözümlenemedi")

    if tls.get("applicable") is False:
        score -= SCORE_WEIGHTS["tls_not_applicable"]
        reasons.append("Hedef HTTPS kullanmıyor")
    elif tls.get("applicable"):
        if not tls.get("chain_valid"):
            score -= SCORE_WEIGHTS["tls_invalid_chain"]
            reasons.append("TLS sertifika zinciri geçersiz")
        else:
            days_remaining = tls.get("days_remaining")
            if days_remaining is not None and days_remaining < 0:
                score -= SCORE_WEIGHTS["tls_expired"]
                reasons.append("TLS sertifikasının süresi dolmuş")
            elif days_remaining is not None and days_remaining <= CERT_EXPIRY_SCORE_WARN_DAYS:
                score -= SCORE_WEIGHTS["tls_expiring_soon"]
                reasons.append(f"TLS sertifikasının bitişine {days_remaining} gün kaldı")

    if not redirect.get("redirects_to_https"):
        score -= SCORE_WEIGHTS["no_https_redirect"]
        reasons.append("HTTP, HTTPS'e yönlendirilmiyor")

    for name, info in (headers.get("security_headers") or {}).items():
        if not info.get("present"):
            score -= SCORE_WEIGHTS["missing_security_header"]
            reasons.append(f"{name} başlığı eksik")

    for name, info in (headers.get("info_leak") or {}).items():
        if info.get("reveals_version"):
            score -= SCORE_WEIGHTS["version_leak"]
            reasons.append(f"{name} başlığı sürüm bilgisi sızdırıyor")

    content = results.get("content") or {}
    if content.get("critical_changed"):
        score -= SCORE_WEIGHTS["content_critical_change"]
        reasons.append("Sayfa başlığı veya H1 metni temel çizgiden değişti")

    score = max(0, min(100, score))
    return {"score": score, "letter_grade": letter_grade(score), "reasons": reasons}
