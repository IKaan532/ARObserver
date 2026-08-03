import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.checks.dns import check_dns
from app.checks.headers import check_headers
from app.checks.reachability import check_reachability
from app.checks.redirect import check_https_redirect
from app.checks.tls import check_tls
from app.config import settings
from app.database import SessionLocal
from app.models import Alert, Check, Target
from app.scoring import calculate_score
from app.targets_loader import sync_targets

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

TARGET_JOB_PREFIX = "check-target-"
RELOAD_JOB_ID = "reload-targets"
RETENTION_JOB_ID = "cleanup-retention"
RELOAD_INTERVAL_SECONDS = 60
RETENTION_INTERVAL_HOURS = 24


def _target_job_id(target_id: int) -> str:
    return f"{TARGET_JOB_PREFIX}{target_id}"


async def run_target_check(target_id: int) -> None:
    with SessionLocal() as db:
        target = db.get(Target, target_id)
        if target is None:
            return
        url = target.url

    reachability, redirect, headers = await asyncio.gather(
        check_reachability(url),
        check_https_redirect(url),
        check_headers(url),
    )
    dns = await asyncio.to_thread(check_dns, url)
    tls = await asyncio.to_thread(check_tls, url)

    results = {"reachability": reachability, "redirect": redirect, "dns": dns, "tls": tls, "headers": headers}
    scoring = calculate_score(results)

    cert_expiry_date = None
    if tls.get("valid_to"):
        cert_expiry_date = datetime.fromisoformat(tls["valid_to"]).replace(tzinfo=None)

    with SessionLocal() as db:
        db.add(
            Check(
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
            )
        )
        db.commit()
    logger.info("target %s checked: score=%s grade=%s", url, scoring["score"], scoring["letter_grade"])


def reload_targets() -> None:
    with SessionLocal() as db:
        sync_targets(db)
        target_data = [(target.id, target.interval_minutes) for target in db.query(Target).all()]

    current_ids = {job.id for job in scheduler.get_jobs() if job.id.startswith(TARGET_JOB_PREFIX)}
    desired_ids = {_target_job_id(target_id) for target_id, _ in target_data}

    for job_id in current_ids - desired_ids:
        scheduler.remove_job(job_id)

    for target_id, interval_minutes in target_data:
        job_id = _target_job_id(target_id)
        trigger = IntervalTrigger(minutes=interval_minutes)
        existing_job = scheduler.get_job(job_id)
        if existing_job is None:
            scheduler.add_job(run_target_check, trigger=trigger, args=[target_id], id=job_id)
        elif existing_job.trigger.interval != trigger.interval:
            scheduler.reschedule_job(job_id, trigger=trigger)


def cleanup_old_records() -> None:
    cutoff = datetime.utcnow() - timedelta(days=settings.retention_days)
    with SessionLocal() as db:
        db.query(Check).filter(Check.checked_at < cutoff).delete()
        db.query(Alert).filter(Alert.resolved_at.isnot(None), Alert.resolved_at < cutoff).delete()
        db.commit()


def start_scheduler() -> None:
    reload_targets()
    scheduler.add_job(reload_targets, trigger=IntervalTrigger(seconds=RELOAD_INTERVAL_SECONDS), id=RELOAD_JOB_ID)
    scheduler.add_job(
        cleanup_old_records, trigger=IntervalTrigger(hours=RETENTION_INTERVAL_HOURS), id=RETENTION_JOB_ID
    )
    scheduler.start()


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
