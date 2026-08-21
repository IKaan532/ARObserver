import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from sqlalchemy import desc

from app.alerting.rules import cleanup_legacy_cert_expiry_alerts, evaluate_rules, notify, to_alert_payloads
from app.checks.content import check_content, compare_fingerprint
from app.checks.ct_log import check_certificate_transparency
from app.checks.dns import check_dns, check_dns_hygiene, check_dns_records
from app.checks.domain_expiry import check_domain_expiry
from app.checks.reputation import check_reputation
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
    trigger = IntervalTrigger(minutes=interval_minutes, jitter=settings.scheduler_jitter_seconds)
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
    dns.update(await asyncio.to_thread(check_dns_hygiene, url))
    dns["records"] = await asyncio.to_thread(check_dns_records, url)
    tls = await asyncio.to_thread(check_tls, url)

    fingerprint = content.get("fingerprint")
    baseline_established = False
    if reachability.get("reachable") and fingerprint is not None and baseline_fingerprint is None:
        baseline_fingerprint = fingerprint
        baseline_established = True

    comparison = compare_fingerprint(baseline_fingerprint if not baseline_established else None, fingerprint or {})

    timing = reachability.get("timing")
    compression = (
        {"content_encoding": timing.get("content_encoding"), "body_size_bytes": timing.get("body_size_bytes")}
        if timing
        else None
    )

    results = {
        "reachability": reachability,
        "redirect": redirect,
        "dns": dns,
        "tls": tls,
        "headers": headers,
        "content": comparison,
        "compression": compression,
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
            network_issue=reachability.get("network_issue", False),
            dns_result=dns,
            redirect_result=redirect,
            tls_result=tls,
            headers_result=headers,
            cert_expiry_date=cert_expiry_date,
            score=scoring["score"],
            letter_grade=scoring["letter_grade"],
            score_reasons=scoring["reasons"],
            content_result=content_result,
            timing_result=timing,
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

        alert_payloads = to_alert_payloads(new_alerts)

    await asyncio.to_thread(notify, alert_payloads)

    logger.info("target %s checked: score=%s grade=%s", url, scoring["score"], scoring["letter_grade"])

    if settings.ct_log_check_enabled:
        await _maybe_check_certificate_transparency(target_id, url, tls)

    await _maybe_check_domain_expiry(target_id, url)
    await _maybe_check_reputation(target_id, url, dns.get("ip_addresses") or [])


async def _maybe_check_reputation(target_id: int, url: str, ip_addresses: list[str]) -> None:
    now = datetime.utcnow()
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        if target.reputation_checked_at is not None and now - target.reputation_checked_at < timedelta(hours=24):
            return
        previous_result = target.reputation_result or {}

    ipv4 = next((ip for ip in ip_addresses if ip.count(".") == 3), None)
    result = await check_reputation(ipv4, url)

    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is not None:
            target.reputation_checked_at = datetime.utcnow()
            target.reputation_result = {
                "dnsbl_flagged": (
                    result["dnsbl_flagged"] if result["dnsbl_flagged"] is not None else previous_result.get("dnsbl_flagged")
                ),
                "safe_browsing_flagged": (
                    result["safe_browsing_flagged"]
                    if result["safe_browsing_flagged"] is not None
                    else previous_result.get("safe_browsing_flagged")
                ),
                "safe_browsing_configured": result["safe_browsing_configured"],
            }
            db.commit()


async def _maybe_check_domain_expiry(target_id: int, url: str) -> None:
    now = datetime.utcnow()
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        if target.domain_expiry_checked_at is not None and now - target.domain_expiry_checked_at < timedelta(
            hours=24
        ):
            return

    hostname = urlparse(url).hostname
    if not hostname:
        return

    result = await check_domain_expiry(hostname)

    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is not None:
            target.domain_expiry_checked_at = datetime.utcnow()
            if result["expiry_date"] is not None:
                target.domain_expiry_date = result["expiry_date"]
            db.commit()


async def _maybe_check_certificate_transparency(target_id: int, url: str, tls: dict) -> None:
    now = datetime.utcnow()
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        if target.ct_log_checked_at is not None and now - target.ct_log_checked_at < timedelta(hours=24):
            return

    hostname = urlparse(url).hostname
    if not hostname:
        return

    known_names = {hostname}
    chain = tls.get("chain") or []
    if chain:
        known_names.update(chain[0].get("san") or [])

    result = await asyncio.to_thread(check_certificate_transparency, hostname, known_names)

    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is not None:
            target.ct_log_result = result
            target.ct_log_checked_at = datetime.utcnow()
            db.commit()


def cleanup_old_records() -> None:
    cutoff = datetime.utcnow() - timedelta(days=settings.retention_days)
    with SessionLocal() as db:
        db.query(Check).filter(Check.checked_at < cutoff).delete()
        db.query(Alert).filter(Alert.resolved_at.isnot(None), Alert.resolved_at < cutoff).delete()
        db.commit()


def start_scheduler() -> None:
    with SessionLocal() as db:
        seed_targets_if_empty(db)
        cleanup_legacy_cert_expiry_alerts(db)
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
