import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, Check, Target

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    targets = db.query(Target).order_by(Target.name).all()
    cards = []
    for target in targets:
        last_check = db.query(Check).filter(Check.target_id == target.id).order_by(desc(Check.checked_at)).first()
        cert_days_remaining = None
        if last_check and last_check.tls_result:
            cert_days_remaining = last_check.tls_result.get("days_remaining")
        cards.append({"target": target, "last_check": last_check, "cert_days_remaining": cert_days_remaining})
    return templates.TemplateResponse(request, "index.html", {"cards": cards})


@router.get("/targets/{target_id}", response_class=HTMLResponse)
def target_detail(request: Request, target_id: int, db: Session = Depends(get_db)):
    target = db.get(Target, target_id)
    if target is None:
        return HTMLResponse("Hedef bulunamadı", status_code=404)

    since = datetime.utcnow() - timedelta(days=30)
    checks = (
        db.query(Check)
        .filter(Check.target_id == target_id, Check.checked_at >= since)
        .order_by(Check.checked_at)
        .all()
    )
    last_check = checks[-1] if checks else None
    open_alerts = (
        db.query(Alert)
        .filter(Alert.target_id == target_id, Alert.resolved_at.is_(None))
        .order_by(desc(Alert.created_at))
        .all()
    )

    chart_data = {
        "labels": [check.checked_at.strftime("%d.%m %H:%M") for check in checks],
        "response_times": [check.response_time_ms for check in checks],
        "scores": [check.score for check in checks],
    }

    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "target": target,
            "last_check": last_check,
            "open_alerts": open_alerts,
            "chart_data_json": json.dumps(chart_data, ensure_ascii=False),
        },
    )
