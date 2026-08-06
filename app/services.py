from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import desc

from app.checks.headers import SECURITY_HEADERS
from app.config import settings
from app.database import SessionLocal
from app.models import Alert, Check, Target
from app.scoring import letter_grade

RANKING_LIMIT = 5

CHART_WINDOW_MINUTES = 15
MAX_CHART_POINTS = 50
UPTIME_TIMELINE_DAYS = 30
DOWNTIME_INCIDENT_LIMIT = 20

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
                "expected_status": target.expected_status,
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
            "expected_status": target.expected_status,
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
    name: str,
    url: str,
    interval_minutes: int,
    tags: list[str],
    expected_keyword: str | None,
    expected_status: int = 200,
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
            expected_status=expected_status,
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
    expected_status: int = 200,
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
        target.expected_status = expected_status
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
        "timing_result": check.timing_result,
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


def get_overview_summary() -> dict:
    with SessionLocal() as db:
        targets = db.query(Target).all()
        last_checks = {}
        for target in targets:
            last_checks[target.id] = (
                db.query(Check).filter(Check.target_id == target.id).order_by(desc(Check.checked_at)).first()
            )
        open_alerts_count = db.query(Alert).filter(Alert.resolved_at.is_(None)).count()

    scored = [last_checks[t.id] for t in targets if last_checks[t.id] is not None and last_checks[t.id].score is not None]
    healthy_count = sum(1 for check in last_checks.values() if check is not None and check.status_code is not None)
    average_score = round(sum(check.score for check in scored) / len(scored), 1) if scored else None

    distribution = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for check in last_checks.values():
        if check is not None and check.letter_grade in distribution:
            distribution[check.letter_grade] += 1

    return {
        "total_targets": len(targets),
        "healthy_count": healthy_count,
        "open_alerts_count": open_alerts_count,
        "average_score": average_score,
        "average_grade": letter_grade(round(average_score)) if average_score is not None else None,
        "grade_distribution": distribution,
    }


def get_rankings() -> dict:
    with SessionLocal() as db:
        targets = db.query(Target).all()
        entries = []
        for target in targets:
            last_check = (
                db.query(Check).filter(Check.target_id == target.id).order_by(desc(Check.checked_at)).first()
            )
            if last_check is not None:
                entries.append((target, last_check))

    lowest_grade = sorted(
        ({"id": t.id, "name": t.name, "score": c.score, "letter_grade": c.letter_grade} for t, c in entries if c.score is not None),
        key=lambda entry: entry["score"],
    )[:RANKING_LIMIT]

    slowest = sorted(
        (
            {"id": t.id, "name": t.name, "response_time_ms": c.response_time_ms}
            for t, c in entries
            if c.response_time_ms is not None
        ),
        key=lambda entry: entry["response_time_ms"],
        reverse=True,
    )[:RANKING_LIMIT]

    return {"lowest_grade": lowest_grade, "slowest": slowest}


def get_header_matrix() -> dict:
    with SessionLocal() as db:
        targets = db.query(Target).order_by(Target.name).all()
        rows = []
        for target in targets:
            last_check = (
                db.query(Check).filter(Check.target_id == target.id).order_by(desc(Check.checked_at)).first()
            )
            security_headers = (last_check.headers_result or {}).get("security_headers") if last_check else None
            row = {"id": target.id, "name": target.name}
            for header in SECURITY_HEADERS:
                if security_headers is None:
                    row[header] = None
                else:
                    row[header] = security_headers.get(header, {}).get("present", False)
            rows.append(row)
    return {"headers": SECURITY_HEADERS, "rows": rows}


def get_certificate_calendar() -> list[dict]:
    with SessionLocal() as db:
        targets = db.query(Target).order_by(Target.name).all()
        entries = []
        for target in targets:
            last_check = (
                db.query(Check).filter(Check.target_id == target.id).order_by(desc(Check.checked_at)).first()
            )
            if last_check is None:
                continue
            tls_result = last_check.tls_result or {}
            days_remaining = tls_result.get("days_remaining")
            if not tls_result.get("applicable") or days_remaining is None:
                continue
            entries.append(
                {
                    "id": target.id,
                    "name": target.name,
                    "days_remaining": days_remaining,
                    "expiry_date": local_dt(last_check.cert_expiry_date, "%d.%m.%Y")
                    if last_check.cert_expiry_date
                    else None,
                }
            )
    entries.sort(key=lambda entry: entry["days_remaining"])
    return entries


def get_uptime_stats(target_id: int) -> dict:
    now = datetime.utcnow()
    with SessionLocal() as db:
        stats = {}
        for label, days in (("uptime_7d", 7), ("uptime_30d", 30)):
            since = now - timedelta(days=days)
            rows = (
                db.query(Check.status_code)
                .filter(Check.target_id == target_id, Check.checked_at >= since)
                .all()
            )
            if not rows:
                stats[label] = None
                continue
            up = sum(1 for (status_code,) in rows if status_code is not None)
            stats[label] = round(100 * up / len(rows), 1)
        return stats


def get_uptime_timeline(target_id: int, days: int = UPTIME_TIMELINE_DAYS) -> list[dict]:
    today_local = datetime.now(_display_tz).date()
    start_date = today_local - timedelta(days=days - 1)
    window_start_utc = (
        datetime.combine(start_date, datetime.min.time())
        .replace(tzinfo=_display_tz)
        .astimezone(ZoneInfo("UTC"))
        .replace(tzinfo=None)
    )

    with SessionLocal() as db:
        checks = (
            db.query(Check.checked_at, Check.status_code)
            .filter(Check.target_id == target_id, Check.checked_at >= window_start_utc)
            .order_by(Check.checked_at)
            .all()
        )

    buckets: dict = {}
    for checked_at, status_code in checks:
        day = to_local(checked_at).date()
        buckets.setdefault(day, []).append(status_code is not None)

    timeline = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        results = buckets.get(day)
        if not results:
            timeline.append({"date": day.strftime("%d.%m"), "uptime_pct": None, "status": "no_data"})
            continue
        pct = round(100 * sum(results) / len(results), 1)
        status = "up" if pct == 100 else "down" if pct == 0 else "partial"
        timeline.append({"date": day.strftime("%d.%m"), "uptime_pct": pct, "status": status})
    return timeline


def get_downtime_incidents(
    target_id: int, days: int = UPTIME_TIMELINE_DAYS, limit: int = DOWNTIME_INCIDENT_LIMIT
) -> list[dict]:
    since = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as db:
        checks = (
            db.query(Check.checked_at, Check.status_code)
            .filter(Check.target_id == target_id, Check.checked_at >= since)
            .order_by(Check.checked_at)
            .all()
        )

    raw_incidents = []
    incident_start = None
    for checked_at, status_code in checks:
        is_down = status_code is None
        if is_down and incident_start is None:
            incident_start = checked_at
        elif not is_down and incident_start is not None:
            raw_incidents.append({"start": incident_start, "end": checked_at, "ongoing": False})
            incident_start = None
    if incident_start is not None:
        raw_incidents.append({"start": incident_start, "end": None, "ongoing": True})

    raw_incidents.reverse()
    incidents = []
    for incident in raw_incidents[:limit]:
        end = incident["end"] or datetime.utcnow()
        duration_minutes = round((end - incident["start"]).total_seconds() / 60)
        incidents.append(
            {
                "start": local_dt(incident["start"]),
                "end": local_dt(incident["end"]) if incident["end"] else None,
                "ongoing": incident["ongoing"],
                "duration_minutes": duration_minutes,
            }
        )
    return incidents


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

    points = []
    for check in checks:
        timing = check.timing_result or {}
        points.append(
            {
                "checked_at": check.checked_at,
                "label": local_dt(check.checked_at, "%H:%M:%S"),
                "response_time_ms": check.response_time_ms,
                "score": check.score,
                "dns_ms": timing.get("dns_ms"),
                "tcp_ms": timing.get("tcp_ms"),
                "tls_ms": timing.get("tls_ms"),
                "ttfb_ms": timing.get("ttfb_ms"),
                "download_ms": timing.get("download_ms"),
                "body_size_kb": round(timing["body_size_bytes"] / 1024, 2) if timing.get("body_size_bytes") else None,
            }
        )
    return points
