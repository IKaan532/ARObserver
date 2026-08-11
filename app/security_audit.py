from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.config import INFO_LEAK_RULES, SECURITY_HEADER_RULES


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


CheckSetFn = Callable[[dict], list[SecurityCheckResult]]

_CHECK_SETS: list[CheckSetFn] = [_security_header_checks]


def run_security_checks(check: dict | None) -> list[SecurityCheckResult]:
    if not check:
        return []
    results: list[SecurityCheckResult] = []
    for check_set in _CHECK_SETS:
        results.extend(check_set(check))
    return results
