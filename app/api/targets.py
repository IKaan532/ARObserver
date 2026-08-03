from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Check, Target
from app.schemas import CheckSummary, TargetOut

router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


@router.get("", response_model=list[TargetOut])
def list_targets(db: Session = Depends(get_db)):
    targets = db.query(Target).order_by(Target.name).all()
    result = []
    for target in targets:
        last_check = (
            db.query(Check).filter(Check.target_id == target.id).order_by(desc(Check.checked_at)).first()
        )
        result.append(
            TargetOut(
                id=target.id,
                name=target.name,
                url=target.url,
                interval_minutes=target.interval_minutes,
                tags=target.tags,
                last_check=CheckSummary.model_validate(last_check) if last_check else None,
            )
        )
    return result
