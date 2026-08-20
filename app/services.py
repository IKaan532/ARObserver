import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import case, desc, func, select

from app.checks import deep_check
from app.checks.headers import SECURITY_HEADERS
from app.config import settings
from app.database import SessionLocal
from app.models import Alert, Check, Target
from app.scoring import letter_grade, recompute_score_breakdown

_deep_check_running: set[int] = set()

RANKING_LIMIT = 5

CHART_WINDOW_MINUTES = 15
MAX_CHART_POINTS = 50
UPTIME_TIMELINE_DAYS = 30
DOWNTIME_INCIDENT_LIMIT = 20
RESPONSE_TIME_PERCENTILE_DAYS = 7
SCORE_HEATMAP_DAYS = 30
EVENT_FEED_LIMIT = 50

_display_tz = ZoneInfo(settings.display_timezone)


def to_local(value: datetime) -> datetime:
    return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(_display_tz)


def local_dt(value: datetime, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return to_local(value).strftime(fmt)


def local_naive_to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=_display_tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def get_latest_checks_by_target(db) -> dict[int, Check]:
    row_number = func.row_number().over(
        partition_by=Check.target_id, order_by=(desc(Check.checked_at), desc(Check.id))
    ).label("rn")
    ranked = select(Check.id, row_number).subquery()
    latest_ids = [row[0] for row in db.query(ranked.c.id).filter(ranked.c.rn == 1).all()]
    if not latest_ids:
        return {}
    checks = db.query(Check).filter(Check.id.in_(latest_ids)).all()
    return {check.target_id: check for check in checks}


HEARTBEAT_LIMIT = 20


def get_target_heartbeats(limit: int = HEARTBEAT_LIMIT) -> dict[int, list[bool | None]]:
    heartbeats: dict[int, list[bool | None]] = {}
    with SessionLocal() as db:
        target_ids = [target_id for (target_id,) in db.query(Target.id).all()]
        for target_id in target_ids:
            rows = (
                db.query(Check.status_code)
                .filter(Check.target_id == target_id, Check.network_issue.is_(False))
                .order_by(desc(Check.checked_at))
                .limit(limit)
                .all()
            )
            heartbeats[target_id] = [status_code is not None for (status_code,) in reversed(rows)]
    return heartbeats


def list_groups() -> list[str]:
    with SessionLocal() as db:
        tag_lists = db.query(Target.tags).all()
    return sorted({tag for (tags,) in tag_lists for tag in (tags or [])})


def list_target_cards() -> list[dict]:
    with SessionLocal() as db:
        targets = db.query(Target).order_by(Target.name).all()
        last_checks = get_latest_checks_by_target(db)
        open_alert_target_ids = {
            row[0] for row in db.query(Alert.target_id).filter(Alert.resolved_at.is_(None)).distinct().all()
        }
        cards = []
        for target in targets:
            last_check = last_checks.get(target.id)
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
                    "score": last_check.score if last_check else None,
                    "status_code": last_check.status_code if last_check else None,
                    "network_issue": last_check.network_issue if last_check else False,
                    "checked_at": local_dt(last_check.checked_at) if last_check else None,
                    "cert_days_remaining": cert_days_remaining,
                    "has_open_alerts": target.id in open_alert_target_ids,
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
            "maintenance_start": target.maintenance_start,
            "maintenance_end": target.maintenance_end,
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
    maintenance_start: datetime | None = None,
    maintenance_end: datetime | None = None,
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
            maintenance_start=maintenance_start,
            maintenance_end=maintenance_end,
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
    maintenance_start: datetime | None = None,
    maintenance_end: datetime | None = None,
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
        target.maintenance_start = maintenance_start
        target.maintenance_end = maintenance_end
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
        "id": check.id,
        "checked_at": local_dt(check.checked_at),
        "status_code": check.status_code,
        "network_issue": check.network_issue,
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


async def check_deep_check_service_available() -> tuple[bool, str | None]:
    return await deep_check.check_service_available()


def is_deep_check_running(target_id: int) -> bool:
    return target_id in _deep_check_running


async def _run_deep_check_task(target_id: int) -> None:
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        url = target.url

    result = await deep_check.run_deep_check(url)

    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        target.deep_check_result = result
        target.deep_check_at = datetime.utcnow()
        db.commit()


def trigger_deep_check(target_id: int) -> str:
    if is_deep_check_running(target_id):
        return "running"
    _deep_check_running.add(target_id)

    async def runner() -> None:
        try:
            await _run_deep_check_task(target_id)
        finally:
            _deep_check_running.discard(target_id)

    asyncio.create_task(runner())
    return "started"


def get_deep_check_result(target_id: int) -> dict | None:
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None or target.deep_check_result is None:
            return None
        return {
            "result": target.deep_check_result,
            "checked_at": local_dt(target.deep_check_at) if target.deep_check_at else None,
        }


CHECK_HISTORY_LIMIT = 30


def get_check_history(target_id: int, limit: int = CHECK_HISTORY_LIMIT) -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.query(Check.id, Check.checked_at, Check.score, Check.letter_grade)
            .filter(Check.target_id == target_id)
            .order_by(desc(Check.checked_at))
            .limit(limit)
            .all()
        )
    return [
        {
            "id": check_id,
            "checked_at": local_dt(checked_at),
            "label": f"{local_dt(checked_at)} — {score if score is not None else '-'} ({letter_grade or '-'})",
        }
        for check_id, checked_at, score, letter_grade in rows
    ]


def get_check_by_id(check_id: int) -> dict | None:
    with SessionLocal() as db:
        check = db.get(Check, check_id)
        return _serialize_check(check) if check else None


def get_previous_check(target_id: int, before_check_id: int) -> dict | None:
    with SessionLocal() as db:
        reference = db.query(Check.checked_at).filter(Check.id == before_check_id).scalar()
        if reference is None:
            return None
        check = (
            db.query(Check)
            .filter(Check.target_id == target_id, Check.checked_at < reference)
            .order_by(desc(Check.checked_at))
            .first()
        )
    return _serialize_check(check) if check else None


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
            "ct_log_result": target.ct_log_result,
            "ct_log_checked_at": local_dt(target.ct_log_checked_at) if target.ct_log_checked_at else None,
            "reputation_result": target.reputation_result,
            "reputation_checked_at": local_dt(target.reputation_checked_at) if target.reputation_checked_at else None,
        }


def get_event_feed(limit: int = EVENT_FEED_LIMIT) -> list[dict]:
    with SessionLocal() as db:
        targets = db.query(Target).all()
        alerts = db.query(Alert).all()

    target_names = {target.id: target.name for target in targets}

    events = []
    for target in targets:
        events.append((target.created_at, "target_added", f"Hedef eklendi: {target.name}"))
    for alert in alerts:
        name = target_names.get(alert.target_id, "?")
        events.append((alert.created_at, "alert_opened", f"[{alert.alert_type}] {name}: {alert.message}"))
        if alert.resolved_at is not None:
            events.append((alert.resolved_at, "alert_resolved", f"[{alert.alert_type}] {name}: uyarı kapandı"))

    events.sort(key=lambda item: item[0], reverse=True)
    return [
        {"timestamp": local_dt(timestamp, "%d.%m.%Y %H:%M:%S"), "type": kind, "text": text}
        for timestamp, kind, text in events[:limit]
    ]


def get_overview_summary() -> dict:
    with SessionLocal() as db:
        targets = db.query(Target).all()
        last_checks = get_latest_checks_by_target(db)
        open_alerts_count = db.query(Alert).filter(Alert.resolved_at.is_(None)).count()

    scored = [last_checks[t.id] for t in targets if last_checks.get(t.id) is not None and last_checks[t.id].score is not None]
    healthy_count = sum(1 for t in targets if last_checks.get(t.id) is not None and last_checks[t.id].status_code is not None)
    average_score = round(sum(check.score for check in scored) / len(scored), 1) if scored else None

    distribution = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for check in last_checks.values():
        if check is not None and check.letter_grade in distribution:
            distribution[check.letter_grade] += 1

    return {
        "total_targets": len(targets),
        "healthy_count": healthy_count,
        "safe_count": distribution["A"] + distribution["B"] + distribution["C"],
        "open_alerts_count": open_alerts_count,
        "average_score": average_score,
        "average_grade": letter_grade(round(average_score)) if average_score is not None else None,
        "grade_distribution": distribution,
    }


def get_rankings() -> dict:
    with SessionLocal() as db:
        targets = db.query(Target).all()
        last_checks = get_latest_checks_by_target(db)
        entries = [(target, last_checks[target.id]) for target in targets if target.id in last_checks]

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
        last_checks = get_latest_checks_by_target(db)
        rows = []
        for target in targets:
            last_check = last_checks.get(target.id)
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
        last_checks = get_latest_checks_by_target(db)
        entries = []
        for target in targets:
            last_check = last_checks.get(target.id)
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


def get_domain_expiry_calendar() -> list[dict]:
    with SessionLocal() as db:
        targets = db.query(Target).filter(Target.domain_expiry_date.is_not(None)).order_by(Target.name).all()
        entries = [
            {
                "id": target.id,
                "name": target.name,
                "days_remaining": (target.domain_expiry_date - datetime.utcnow()).days,
                "expiry_date": local_dt(target.domain_expiry_date, "%d.%m.%Y"),
            }
            for target in targets
        ]
    entries.sort(key=lambda entry: entry["days_remaining"])
    return entries


def _percentile(sorted_values: list[float], pct: float) -> float:
    if len(sorted_values) == 1:
        return round(sorted_values[0], 1)
    rank = (len(sorted_values) - 1) * (pct / 100)
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    if lower_index == upper_index:
        return round(sorted_values[lower_index], 1)
    lower_weight = upper_index - rank
    upper_weight = rank - lower_index
    return round(sorted_values[lower_index] * lower_weight + sorted_values[upper_index] * upper_weight, 1)


def get_response_time_percentiles(target_id: int, days: int = RESPONSE_TIME_PERCENTILE_DAYS) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as db:
        rows = (
            db.query(Check.response_time_ms)
            .filter(Check.target_id == target_id, Check.checked_at >= since, Check.response_time_ms.isnot(None))
            .all()
        )
    values = sorted(value for (value,) in rows)
    if not values:
        return {"p50": None, "p95": None, "p99": None, "sample_size": 0}
    return {
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "sample_size": len(values),
    }


def get_score_heatmap(days: int = SCORE_HEATMAP_DAYS) -> dict:
    today_local = datetime.now(_display_tz).date()
    start_date = today_local - timedelta(days=days - 1)
    window_start_utc = (
        datetime.combine(start_date, datetime.min.time())
        .replace(tzinfo=_display_tz)
        .astimezone(ZoneInfo("UTC"))
        .replace(tzinfo=None)
    )

    with SessionLocal() as db:
        targets = db.query(Target).order_by(Target.name).all()
        rows = (
            db.query(Check.target_id, Check.checked_at, Check.score)
            .filter(Check.checked_at >= window_start_utc, Check.score.isnot(None))
            .all()
        )

    buckets: dict = {}
    for target_id, checked_at, score in rows:
        day = to_local(checked_at).date()
        buckets.setdefault((target_id, day), []).append(score)

    day_labels = [start_date + timedelta(days=offset) for offset in range(days)]
    data = []
    for target_index, target in enumerate(targets):
        for day_index, day in enumerate(day_labels):
            scores = buckets.get((target.id, day))
            avg_score = round(sum(scores) / len(scores), 1) if scores else None
            data.append([day_index, target_index, avg_score])

    return {
        "targets": [target.name for target in targets],
        "days": [day.strftime("%d.%m") for day in day_labels],
        "data": data,
    }


def _within_maintenance_window(checked_at: datetime, maintenance_start, maintenance_end) -> bool:
    if maintenance_start is None or maintenance_end is None:
        return False
    return maintenance_start <= checked_at <= maintenance_end


def get_uptime_stats(target_id: int) -> dict:
    now = datetime.utcnow()
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        maintenance_start = target.maintenance_start if target else None
        maintenance_end = target.maintenance_end if target else None
        stats = {}
        for label, days in (("uptime_7d", 7), ("uptime_30d", 30)):
            since = now - timedelta(days=days)
            base_filter = [
                Check.target_id == target_id,
                Check.checked_at >= since,
                Check.network_issue.is_(False),
            ]
            if maintenance_start is not None and maintenance_end is not None:
                base_filter.append(
                    ~((Check.checked_at >= maintenance_start) & (Check.checked_at <= maintenance_end))
                )

            total, up = db.query(
                func.count(Check.id),
                func.sum(case((Check.status_code.isnot(None), 1), else_=0)),
            ).filter(*base_filter).one()
            if not total:
                stats[label] = None
                continue
            stats[label] = round(100 * (up or 0) / total, 1)
        return stats


def get_fleet_uptime_stats() -> dict[int, dict]:
    now = datetime.utcnow()
    with SessionLocal() as db:
        targets = (
            db.query(Target.id, Target.name, Target.maintenance_start, Target.maintenance_end)
            .order_by(Target.name)
            .all()
        )
        stats = {
            target_id: {"name": name, "uptime_7d": None, "uptime_30d": None}
            for target_id, name, _maintenance_start, _maintenance_end in targets
        }
        maintenance = {
            target_id: (maintenance_start, maintenance_end)
            for target_id, _name, maintenance_start, maintenance_end in targets
        }

        for label, days in (("uptime_7d", 7), ("uptime_30d", 30)):
            since = now - timedelta(days=days)
            rows = (
                db.query(Check.target_id, Check.checked_at, Check.status_code)
                .filter(Check.checked_at >= since, Check.network_issue.is_(False))
                .all()
            )

            totals: dict[int, int] = {}
            ups: dict[int, int] = {}
            for target_id, checked_at, status_code in rows:
                maintenance_start, maintenance_end = maintenance.get(target_id, (None, None))
                if _within_maintenance_window(checked_at, maintenance_start, maintenance_end):
                    continue
                totals[target_id] = totals.get(target_id, 0) + 1
                if status_code is not None:
                    ups[target_id] = ups.get(target_id, 0) + 1

            for target_id, total in totals.items():
                if target_id in stats:
                    stats[target_id][label] = round(100 * ups.get(target_id, 0) / total, 1)

    return stats


def get_fleet_status() -> list[dict]:
    with SessionLocal() as db:
        targets = db.query(Target.id, Target.name).order_by(Target.name).all()

    heartbeats = get_target_heartbeats()
    entries = []
    for target_id, name in targets:
        hours = heartbeats.get(target_id, [])
        entries.append(
            {
                "id": target_id,
                "name": name,
                "up": hours[-1] if hours else None,
                "hours": hours,
            }
        )
    return entries


def get_fleet_score_breakdowns() -> list[dict]:
    with SessionLocal() as db:
        targets = db.query(Target.id, Target.name).order_by(Target.name).all()
        last_checks = get_latest_checks_by_target(db)
    breakdowns = []
    for target_id, name in targets:
        last_check = last_checks.get(target_id)
        result = recompute_score_breakdown(_serialize_check(last_check)) if last_check else None
        breakdowns.append({"target_id": target_id, "name": name, "result": result})
    return breakdowns


def get_fleet_open_alerts() -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.query(Alert, Target.name)
            .join(Target, Alert.target_id == Target.id)
            .filter(Alert.resolved_at.is_(None))
            .order_by(Target.name, desc(Alert.created_at))
            .all()
        )
    return [
        {
            "target_name": name,
            "alert_type": alert.alert_type,
            "message": alert.message,
            "created_at": local_dt(alert.created_at),
        }
        for alert, name in rows
    ]


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
        target = db.get(Target, target_id)
        maintenance_start = target.maintenance_start if target else None
        maintenance_end = target.maintenance_end if target else None
        checks = (
            db.query(Check.checked_at, Check.status_code)
            .filter(
                Check.target_id == target_id,
                Check.checked_at >= window_start_utc,
                Check.network_issue.is_(False),
            )
            .order_by(Check.checked_at)
            .all()
        )

    buckets: dict = {}
    for checked_at, status_code in checks:
        if _within_maintenance_window(checked_at, maintenance_start, maintenance_end):
            continue
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
        target = db.get(Target, target_id)
        maintenance_start = target.maintenance_start if target else None
        maintenance_end = target.maintenance_end if target else None
        checks = (
            db.query(Check.checked_at, Check.status_code)
            .filter(Check.target_id == target_id, Check.checked_at >= since, Check.network_issue.is_(False))
            .order_by(Check.checked_at)
            .all()
        )

    raw_incidents = []
    incident_start = None
    for checked_at, status_code in checks:
        if _within_maintenance_window(checked_at, maintenance_start, maintenance_end):
            continue
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
