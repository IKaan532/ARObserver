import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from sqlalchemy import desc

from app.alerting.rules import evaluate_rules, notify
from app.checks.content import check_content, compare_fingerprint
from app.checks.dns import check_dns
from app.checks.headers import check_headers
from app.checks.reachability import check_reachability
from app.checks.redirect import check_https_redirect
from app.checks.tls import check_tls
from app.config import SCORING_VERSION, settings
from app.database import SessionLocal
from app.models import Alert, Check, Target
from app.scoring import calculate_score
from app.targets_loader import seed_targets_if_empty

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

TARGET_JOB_PREFIX = "check-target-"
RETENTION_JOB_ID = "cleanup-retention"
RETENTION_INTERVAL_HOURS = 24
MANUAL_TRIGGER_COOLDOWN_SECONDS = 30

_running_target_ids: set[int] = set()
_last_manual_trigger: dict[int, datetime] = {}


def is_target_running(target_id: int) -> bool:
    return target_id in _running_target_ids


def _cooldown_remaining(target_id: int) -> float:
    last = _last_manual_trigger.get(target_id)
    if last is None:
        return 0.0
    elapsed = (datetime.now() - last).total_seconds()
    return max(0.0, MANUAL_TRIGGER_COOLDOWN_SECONDS - elapsed)


async def _run_manual_check(target_id: int) -> None:
    _running_target_ids.add(target_id)
    try:
        await run_target_check(target_id)
    finally:
        _running_target_ids.discard(target_id)


def trigger_manual_check(target_id: int) -> str:
    if is_target_running(target_id):
        return "running"
    if _cooldown_remaining(target_id) > 0:
        return "cooldown"
    _last_manual_trigger[target_id] = datetime.now()
    asyncio.create_task(_run_manual_check(target_id))
    return "started"


def _target_job_id(target_id: int) -> str:
    return f"{TARGET_JOB_PREFIX}{target_id}"


def schedule_target(target_id: int, interval_minutes: int, run_immediately: bool = True) -> None:
    job_id = _target_job_id(target_id)
    trigger = IntervalTrigger(minutes=interval_minutes)
    existing_job = scheduler.get_job(job_id)
    if existing_job is None:
        kwargs = {"next_run_time": datetime.now()} if run_immediately else {}
        scheduler.add_job(run_target_check, trigger=trigger, args=[target_id], id=job_id, **kwargs)
    else:
        scheduler.reschedule_job(job_id, trigger=trigger)


def unschedule_target(target_id: int) -> None:
    job_id = _target_job_id(target_id)
    if scheduler.get_job(job_id) is not None:
        scheduler.remove_job(job_id)


async def run_target_check(target_id: int) -> None:
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        url = target.url
        expected_keyword = target.expected_keyword
        baseline_fingerprint = target.baseline_fingerprint
        previous_content_hash = (
            db.query(Check.content_result)
            .filter(Check.target_id == target_id)
            .order_by(desc(Check.checked_at))
            .limit(1)
            .scalar()
        )

    reachability, redirect, headers, content = await asyncio.gather(
        check_reachability(url),
        check_https_redirect(url),
        check_headers(url),
        check_content(url, expected_keyword),
    )
    dns = await asyncio.to_thread(check_dns, url)
    tls = await asyncio.to_thread(check_tls, url)

    fingerprint = content.get("fingerprint")
    baseline_established = False
    if reachability.get("reachable") and fingerprint is not None and baseline_fingerprint is None:
        baseline_fingerprint = fingerprint
        baseline_established = True

    comparison = compare_fingerprint(baseline_fingerprint if not baseline_established else None, fingerprint or {})

    results = {
        "reachability": reachability,
        "redirect": redirect,
        "dns": dns,
        "tls": tls,
        "headers": headers,
        "content": comparison,
    }
    scoring = calculate_score(results)

    cert_expiry_date = None
    if tls.get("valid_to"):
        cert_expiry_date = datetime.fromisoformat(tls["valid_to"]).replace(tzinfo=None)

    previous_hash = (previous_content_hash or {}).get("content_hash") if previous_content_hash else None
    content_hash = content.get("content_hash")
    hash_changed = previous_hash is not None and content_hash is not None and content_hash != previous_hash

    content_result = {
        "content_hash": content_hash,
        "hash_changed": hash_changed,
        "keyword_found": content.get("keyword_found"),
        "fingerprint": fingerprint,
        "baseline_established": baseline_established,
        "changes": comparison["changes"],
        "critical_changed": comparison["critical_changed"],
        "threshold_exceeded": comparison["threshold_exceeded"],
    }

    with SessionLocal() as db:
        check = Check(
            target_id=target_id,
            status_code=reachability.get("status_code"),
            response_time_ms=reachability.get("response_time_ms"),
            is_timeout=reachability.get("timeout", False),
            error_message=reachability.get("error"),
            dns_result=dns,
            redirect_result=redirect,
            tls_result=tls,
            headers_result=headers,
            cert_expiry_date=cert_expiry_date,
            score=scoring["score"],
            letter_grade=scoring["letter_grade"],
            score_reasons=scoring["reasons"],
            content_result=content_result,
            scoring_version=SCORING_VERSION,
        )
        db.add(check)

        target = db.get(Target, target_id)
        if baseline_established:
            target.baseline_fingerprint = fingerprint

        db.commit()
        db.refresh(check)

        new_alerts = evaluate_rules(db, target, check)
        db.commit()

        notify(new_alerts)

    logger.info("target %s checked: score=%s grade=%s", url, scoring["score"], scoring["letter_grade"])


def cleanup_old_records() -> None:
    cutoff = datetime.utcnow() - timedelta(days=settings.retention_days)
    with SessionLocal() as db:
        db.query(Check).filter(Check.checked_at < cutoff).delete()
        db.query(Alert).filter(Alert.resolved_at.isnot(None), Alert.resolved_at < cutoff).delete()
        db.commit()


def start_scheduler() -> None:
    with SessionLocal() as db:
        seed_targets_if_empty(db)
        active_targets = [
            (target.id, target.interval_minutes) for target in db.query(Target).filter(Target.active.is_(True)).all()
        ]

    for target_id, interval_minutes in active_targets:
        schedule_target(target_id, interval_minutes)

    scheduler.add_job(
        cleanup_old_records, trigger=IntervalTrigger(hours=RETENTION_INTERVAL_HOURS), id=RETENTION_JOB_ID
    )
    scheduler.start()


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
