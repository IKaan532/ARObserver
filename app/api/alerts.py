from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, Target
from app.schemas import AlertOut

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(resolved: Optional[bool] = Query(None), db: Session = Depends(get_db)):
    query = db.query(Alert, Target.name).join(Target, Alert.target_id == Target.id)
    if resolved is True:
        query = query.filter(Alert.resolved_at.isnot(None))
    elif resolved is False:
        query = query.filter(Alert.resolved_at.is_(None))
    rows = query.order_by(desc(Alert.created_at)).all()
    return [
        AlertOut(
            id=alert.id,
            target_id=alert.target_id,
            target_name=target_name,
            alert_type=alert.alert_type,
            message=alert.message,
            created_at=alert.created_at,
            resolved_at=alert.resolved_at,
        )
        for alert, target_name in rows
    ]
