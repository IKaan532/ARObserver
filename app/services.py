from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import desc

from app.config import settings
from app.database import SessionLocal
from app.models import Alert, Check, Target

CHART_WINDOW_MINUTES = 15
MAX_CHART_POINTS = 50

_display_tz = ZoneInfo(settings.display_timezone)


def to_local(value: datetime) -> datetime:
    return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(_display_tz)


def local_dt(value: datetime, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return to_local(value).strftime(fmt)


def list_groups() -> list[str]:
    with SessionLocal() as db:
        tag_lists = db.query(Target.tags).all()
    return sorted({tag for (tags,) in tag_lists for tag in (tags or [])})


def list_target_cards() -> list[dict]:
    with SessionLocal() as db:
        targets = db.query(Target).order_by(Target.name).all()
        cards = []
        for target in targets:
            last_check = (
                db.query(Check).filter(Check.target_id == target.id).order_by(desc(Check.checked_at)).first()
            )
            cert_days_remaining = None
            if last_check and last_check.tls_result:
                cert_days_remaining = last_check.tls_result.get("days_remaining")
            cards.append(
                {
                    "id": target.id,
                    "name": target.name,
                    "url": target.url,
                    "tags": target.tags or [],
                    "letter_grade": last_check.letter_grade if last_check else None,
                    "status_code": last_check.status_code if last_check else None,
                    "checked_at": local_dt(last_check.checked_at) if last_check else None,
                    "cert_days_remaining": cert_days_remaining,
                }
            )
        return cards


def _serialize_check(check: Check) -> dict:
    return {
        "checked_at": local_dt(check.checked_at),
        "status_code": check.status_code,
        "response_time_ms": check.response_time_ms,
        "dns_result": check.dns_result,
        "redirect_result": check.redirect_result,
        "tls_result": check.tls_result,
        "headers_result": check.headers_result,
        "score": check.score,
        "letter_grade": check.letter_grade,
        "score_reasons": check.score_reasons,
        "content_result": check.content_result,
    }


def reset_baseline(target_id: int) -> None:
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        target.baseline_fingerprint = None
        db.commit()


def get_target_detail(target_id: int) -> dict | None:
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return None
        last_check = (
            db.query(Check).filter(Check.target_id == target_id).order_by(desc(Check.checked_at)).first()
        )
        open_alerts = (
            db.query(Alert)
            .filter(Alert.target_id == target_id, Alert.resolved_at.is_(None))
            .order_by(desc(Alert.created_at))
            .all()
        )
        return {
            "id": target.id,
            "name": target.name,
            "url": target.url,
            "interval_minutes": target.interval_minutes,
            "last_check": _serialize_check(last_check) if last_check else None,
            "open_alerts": [
                {"alert_type": alert.alert_type, "message": alert.message, "created_at": local_dt(alert.created_at)}
                for alert in open_alerts
            ],
        }


def get_chart_points(target_id: int, since: datetime | None = None, limit: int = MAX_CHART_POINTS) -> list[dict]:
    with SessionLocal() as db:
        query = db.query(Check).filter(Check.target_id == target_id)
        if since is not None:
            query = query.filter(Check.checked_at > since)
        else:
            window_start = datetime.utcnow() - timedelta(minutes=CHART_WINDOW_MINUTES)
            query = query.filter(Check.checked_at >= window_start)
        checks = query.order_by(Check.checked_at).all()

    if limit and len(checks) > limit:
        checks = checks[-limit:]

    return [
        {
            "checked_at": check.checked_at,
            "label": local_dt(check.checked_at, "%H:%M:%S"),
            "response_time_ms": check.response_time_ms,
            "score": check.score,
        }
        for check in checks
    ]
