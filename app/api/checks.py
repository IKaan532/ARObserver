from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Check, Target
from app.schemas import CheckOut

router = APIRouter(prefix="/api/v1/targets", tags=["checks"])


@router.get("/{target_id}/checks", response_model=list[CheckOut])
def list_checks(target_id: int, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    return (
        db.query(Check).filter(Check.target_id == target_id).order_by(desc(Check.checked_at)).limit(limit).all()
    )
