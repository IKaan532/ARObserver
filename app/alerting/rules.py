import logging
from datetime import datetime

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.alerting.console import ConsoleNotifier
from app.alerting.email import EmailNotifier
from app.checks.headers import SECURITY_HEADERS
from app.config import settings
from app.models import Alert, Check, Target

logger = logging.getLogger(__name__)

GRADE_ORDER = ["A", "B", "C", "D", "F"]


def _grade_rank(grade: str) -> int:
    return GRADE_ORDER.index(grade) if grade in GRADE_ORDER else len(GRADE_ORDER)


def _open_alert_query(db: Session, target_id: int, alert_type: str):
    return db.query(Alert).filter(
        Alert.target_id == target_id, Alert.alert_type == alert_type, Alert.resolved_at.is_(None)
    )


def _maybe_open_alert(db: Session, target_id: int, alert_type: str, message: str) -> Alert | None:
    if _open_alert_query(db, target_id, alert_type).first() is not None:
        return None
    alert = Alert(target_id=target_id, alert_type=alert_type, message=message)
    db.add(alert)
    return alert


def _resolve_alert(db: Session, target_id: int, alert_type: str) -> None:
    alert = _open_alert_query(db, target_id, alert_type).first()
    if alert is not None:
        alert.resolved_at = datetime.utcnow()


def _check_unreachable(db: Session, target: Target, latest_check: Check) -> list[Alert]:
    recent = (
        db.query(Check)
        .filter(Check.target_id == target.id)
        .order_by(desc(Check.checked_at))
        .limit(settings.alert_fail_threshold)
        .all()
    )
    all_failed = len(recent) == settings.alert_fail_threshold and all(c.status_code is None for c in recent)
    if all_failed:
        message = f"Hedef art arda {settings.alert_fail_threshold} kez erişilemedi"
        alert = _maybe_open_alert(db, target.id, "unreachable", message)
        return [alert] if alert else []
    _resolve_alert(db, target.id, "unreachable")
    return []


def _check_cert_expiry(db: Session, target: Target, latest_check: Check) -> list[Alert]:
    days_remaining = (latest_check.tls_result or {}).get("days_remaining")
    new_alerts = []
    for threshold in settings.cert_expiry_warn_days_list:
        alert_type = f"cert_expiry_{threshold}"
        if days_remaining is not None and days_remaining <= threshold:
            message = f"TLS sertifikasının bitişine {days_remaining} gün kaldı"
            alert = _maybe_open_alert(db, target.id, alert_type, message)
            if alert:
                new_alerts.append(alert)
        else:
            _resolve_alert(db, target.id, alert_type)
    return new_alerts


def _check_score_drop(db: Session, target: Target, previous_check: Check | None, latest_check: Check) -> list[Alert]:
    if previous_check is None or previous_check.letter_grade is None or latest_check.letter_grade is None:
        return []
    if _grade_rank(latest_check.letter_grade) <= _grade_rank(previous_check.letter_grade):
        return []
    message = f"Skor notu {previous_check.letter_grade}'den {latest_check.letter_grade}'e düştü"
    alert = Alert(target_id=target.id, alert_type="score_drop", message=message, resolved_at=datetime.utcnow())
    db.add(alert)
    return [alert]


def _check_missing_headers(
    db: Session, target: Target, previous_check: Check | None, latest_check: Check
) -> list[Alert]:
    if previous_check is None:
        return []
    previous_headers = ((previous_check.headers_result or {}).get("security_headers")) or {}
    current_headers = ((latest_check.headers_result or {}).get("security_headers")) or {}
    new_alerts = []
    for header in SECURITY_HEADERS:
        alert_type = f"header_missing_{header}"
        was_present = previous_headers.get(header, {}).get("present")
        is_present = current_headers.get(header, {}).get("present")
        if was_present and not is_present:
            message = f"{header} güvenlik başlığı artık gönderilmiyor"
            alert = _maybe_open_alert(db, target.id, alert_type, message)
            if alert:
                new_alerts.append(alert)
        elif is_present:
            _resolve_alert(db, target.id, alert_type)
    return new_alerts


def _check_keyword_missing(db: Session, target: Target, latest_check: Check) -> list[Alert]:
    if not target.expected_keyword:
        return []
    if latest_check.keyword_found is False:
        message = f"Beklenen anahtar kelime bulunamadı: '{target.expected_keyword}'"
        alert = _maybe_open_alert(db, target.id, "keyword_missing", message)
        return [alert] if alert else []
    _resolve_alert(db, target.id, "keyword_missing")
    return []


def evaluate_rules(db: Session, target: Target, latest_check: Check) -> list[Alert]:
    previous_check = (
        db.query(Check)
        .filter(Check.target_id == target.id, Check.id != latest_check.id)
        .order_by(desc(Check.checked_at))
        .first()
    )

    new_alerts = []
    new_alerts += _check_unreachable(db, target, latest_check)
    new_alerts += _check_cert_expiry(db, target, latest_check)
    new_alerts += _check_score_drop(db, target, previous_check, latest_check)
    new_alerts += _check_missing_headers(db, target, previous_check, latest_check)
    new_alerts += _check_keyword_missing(db, target, latest_check)
    return new_alerts


def _active_notifiers():
    notifiers = [ConsoleNotifier()]
    if settings.smtp_host:
        notifiers.append(EmailNotifier())
    return notifiers


def notify(alerts: list[Alert]) -> None:
    for notifier in _active_notifiers():
        for alert in alerts:
            try:
                notifier.send(alert)
            except Exception as exc:
                logger.error("notifier %s failed: %s", type(notifier).__name__, exc)
