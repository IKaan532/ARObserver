from datetime import datetime, timedelta
from urllib.parse import urlparse
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
                    "active": target.active,
                    "letter_grade": last_check.letter_grade if last_check else None,
                    "status_code": last_check.status_code if last_check else None,
                    "checked_at": local_dt(last_check.checked_at) if last_check else None,
                    "cert_days_remaining": cert_days_remaining,
                }
            )
        return cards


def list_all_targets() -> list[dict]:
    with SessionLocal() as db:
        targets = db.query(Target).order_by(Target.name).all()
        return [
            {
                "id": target.id,
                "name": target.name,
                "url": target.url,
                "interval_minutes": target.interval_minutes,
                "tags": target.tags or [],
                "expected_keyword": target.expected_keyword,
                "active": target.active,
            }
            for target in targets
        ]


def get_editable_target(target_id: int) -> dict | None:
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return None
        return {
            "id": target.id,
            "name": target.name,
            "url": target.url,
            "interval_minutes": target.interval_minutes,
            "tags": target.tags or [],
            "expected_keyword": target.expected_keyword,
            "active": target.active,
        }


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Geçersiz url — http:// veya https:// ile başlamalı")


def _ensure_url_unique(db, url: str, exclude_target_id: int | None = None) -> None:
    query = db.query(Target).filter(Target.url == url)
    if exclude_target_id is not None:
        query = query.filter(Target.id != exclude_target_id)
    if query.first() is not None:
        raise ValueError("Bu url zaten izleniyor")


def create_target(
    name: str, url: str, interval_minutes: int, tags: list[str], expected_keyword: str | None
) -> int:
    from app.scheduler import schedule_target, trigger_manual_check

    _validate_url(url)
    with SessionLocal() as db:
        _ensure_url_unique(db, url)
        target = Target(
            name=name,
            url=url,
            interval_minutes=interval_minutes,
            tags=tags,
            expected_keyword=expected_keyword or None,
        )
        db.add(target)
        db.commit()
        db.refresh(target)
        target_id = target.id

    schedule_target(target_id, interval_minutes, run_immediately=False)
    trigger_manual_check(target_id)
    return target_id


def update_target(
    target_id: int,
    name: str,
    url: str,
    interval_minutes: int,
    tags: list[str],
    expected_keyword: str | None,
    active: bool,
) -> None:
    from app.scheduler import schedule_target, unschedule_target

    _validate_url(url)
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        _ensure_url_unique(db, url, exclude_target_id=target_id)
        was_active = target.active
        target.name = name
        target.url = url
        target.interval_minutes = interval_minutes
        target.tags = tags
        target.expected_keyword = expected_keyword or None
        target.active = active
        db.commit()

    if active:
        schedule_target(target_id, interval_minutes)
    elif was_active:
        unschedule_target(target_id)


def set_target_active(target_id: int, active: bool) -> None:
    from app.scheduler import schedule_target, unschedule_target

    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        target.active = active
        interval_minutes = target.interval_minutes
        db.commit()

    if active:
        schedule_target(target_id, interval_minutes)
    else:
        unschedule_target(target_id)


def delete_target(target_id: int) -> None:
    from app.scheduler import unschedule_target

    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        db.delete(target)
        db.commit()

    unschedule_target(target_id)


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
