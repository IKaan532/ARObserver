from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.config import INFO_LEAK_RULES, SECURITY_HEADER_RULES, TLS_CERTIFICATE_RULES, TLS_PROTOCOL_RULES


class SecurityCheckStatus(str, Enum):
    PASS = "geçti"
    WARN = "uyarı"
    FAIL = "kaldı"


@dataclass
class SecurityCheckResult:
    name: str
    status: SecurityCheckStatus
    weight: int
    detail: str


def _security_header_checks(check: dict) -> list[SecurityCheckResult]:
    headers_result = (check or {}).get("headers_result") or {}
    if not headers_result.get("reachable", False):
        return []

    results: list[SecurityCheckResult] = []

    security_headers = headers_result.get("security_headers") or {}
    for name, rule in SECURITY_HEADER_RULES.items():
        info = security_headers.get(name, {})
        if info.get("present"):
            results.append(
                SecurityCheckResult(name, SecurityCheckStatus.PASS, rule["points"], f"Değer: {info.get('value')}")
            )
        else:
            results.append(SecurityCheckResult(name, SecurityCheckStatus.FAIL, rule["points"], rule["message"]))

    leak_rule = INFO_LEAK_RULES["version_leak"]
    info_leak = headers_result.get("info_leak") or {}
    for name, info in info_leak.items():
        label = f"{name} (bilgi sızıntısı)"
        if info.get("reveals_version"):
            results.append(
                SecurityCheckResult(
                    label, SecurityCheckStatus.FAIL, leak_rule["points"], leak_rule["message"].format(header=name)
                )
            )
        elif info.get("present"):
            results.append(
                SecurityCheckResult(label, SecurityCheckStatus.PASS, 0, f"Değer: {info.get('value')}, sürüm bilgisi yok")
            )
        else:
            results.append(SecurityCheckResult(label, SecurityCheckStatus.PASS, 0, "Başlık gönderilmiyor"))

    return results


def _tls_health_checks(check: dict) -> list[SecurityCheckResult]:
    tls_result = (check or {}).get("tls_result") or {}
    if not tls_result:
        return []

    if not tls_result.get("applicable"):
        rule = TLS_CERTIFICATE_RULES["https_not_used"]
        return [
            SecurityCheckResult(
                "HTTPS Kullanımı",
                SecurityCheckStatus.FAIL,
                rule["points"],
                "Hedef HTTPS kullanmıyor — sertifika ve TLS sürüm/şifre kontrolleri uygulanamıyor.",
            )
        ]

    results: list[SecurityCheckResult] = []

    if tls_result.get("chain_valid"):
        results.append(SecurityCheckResult("Sertifika Zinciri", SecurityCheckStatus.PASS, 0, "Geçerli"))

        days = tls_result.get("days_remaining")
        if days is not None and days < 0:
            rule = TLS_CERTIFICATE_RULES["expired"]
            results.append(SecurityCheckResult("Sertifika Süresi", SecurityCheckStatus.FAIL, rule["points"], rule["message"]))
        elif days is not None and days < 7:
            rule = TLS_CERTIFICATE_RULES["expiring_under_7_days"]
            results.append(
                SecurityCheckResult("Sertifika Süresi", SecurityCheckStatus.FAIL, rule["points"], rule["message"].format(days=days))
            )
        elif days is not None and days < 14:
            rule = TLS_CERTIFICATE_RULES["expiring_under_14_days"]
            results.append(
                SecurityCheckResult("Sertifika Süresi", SecurityCheckStatus.FAIL, rule["points"], rule["message"].format(days=days))
            )
        elif days is not None and days < 30:
            rule = TLS_CERTIFICATE_RULES["expiring_under_30_days"]
            results.append(
                SecurityCheckResult("Sertifika Süresi", SecurityCheckStatus.FAIL, rule["points"], rule["message"].format(days=days))
            )
        else:
            detail = f"Kalan gün: {days}" if days is not None else "Bilinmiyor"
            results.append(SecurityCheckResult("Sertifika Süresi", SecurityCheckStatus.PASS, 0, detail))
    else:
        rule = TLS_CERTIFICATE_RULES["invalid_chain"]
        results.append(SecurityCheckResult("Sertifika Zinciri", SecurityCheckStatus.FAIL, rule["points"], rule["message"]))
        results.append(
            SecurityCheckResult(
                "Sertifika Süresi", SecurityCheckStatus.WARN, 0, "Sertifika zinciri geçersiz olduğu için ölçülemedi"
            )
        )

    if tls_result.get("cipher_name") is None:
        for name in ("TLS 1.0 / 1.1", "TLS 1.3", "Şifre Takımı"):
            results.append(SecurityCheckResult(name, SecurityCheckStatus.WARN, 0, "Test edilemedi (bağlantı kurulamadı)"))
        return results

    old_protocols_supported = tls_result.get("old_protocols_supported")
    if old_protocols_supported is None:
        results.append(SecurityCheckResult("TLS 1.0 / 1.1", SecurityCheckStatus.WARN, 0, "Test edilemedi"))
    elif old_protocols_supported:
        rule = TLS_PROTOCOL_RULES["weak_protocol"]
        results.append(SecurityCheckResult("TLS 1.0 / 1.1", SecurityCheckStatus.FAIL, rule["points"], rule["message"]))
    else:
        results.append(SecurityCheckResult("TLS 1.0 / 1.1", SecurityCheckStatus.PASS, 0, "Reddediliyor"))

    tls13_supported = tls_result.get("tls_1_3_supported")
    if tls13_supported is None:
        results.append(SecurityCheckResult("TLS 1.3", SecurityCheckStatus.WARN, 0, "Test edilemedi"))
    elif tls13_supported is False:
        rule = TLS_PROTOCOL_RULES["no_tls13"]
        results.append(SecurityCheckResult("TLS 1.3", SecurityCheckStatus.FAIL, rule["points"], rule["message"]))
    else:
        results.append(SecurityCheckResult("TLS 1.3", SecurityCheckStatus.PASS, 0, "Destekleniyor"))

    if tls_result.get("weak_cipher"):
        rule = TLS_PROTOCOL_RULES["weak_cipher"]
        results.append(
            SecurityCheckResult(
                "Şifre Takımı",
                SecurityCheckStatus.FAIL,
                rule["points"],
                rule["message"].format(cipher=tls_result.get("cipher_name")),
            )
        )
    else:
        cipher_detail = f"{tls_result.get('cipher_name')} ({tls_result.get('negotiated_protocol')})"
        results.append(SecurityCheckResult("Şifre Takımı", SecurityCheckStatus.PASS, 0, cipher_detail))

    return results


CheckSetFn = Callable[[dict], list[SecurityCheckResult]]

_CHECK_SETS: list[CheckSetFn] = [_security_header_checks, _tls_health_checks]


def run_security_checks(check: dict | None) -> list[SecurityCheckResult]:
    if not check:
        return []
    results: list[SecurityCheckResult] = []
    for check_set in _CHECK_SETS:
        results.extend(check_set(check))
    return results
