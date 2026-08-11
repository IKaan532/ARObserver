from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Target
from app.schemas import CheckSummary, TargetOut
from app.services import get_latest_checks_by_target

router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


@router.get("", response_model=list[TargetOut])
def list_targets(db: Session = Depends(get_db)):
    targets = db.query(Target).order_by(Target.name).all()
    last_checks = get_latest_checks_by_target(db)
    return [
        TargetOut(
            id=target.id,
            name=target.name,
            url=target.url,
            interval_minutes=target.interval_minutes,
            tags=target.tags,
            last_check=CheckSummary.model_validate(last_checks[target.id]) if target.id in last_checks else None,
        )
        for target in targets
    ]
