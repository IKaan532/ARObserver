from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CheckSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    checked_at: datetime
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    score: Optional[int] = None
    letter_grade: Optional[str] = None
    cert_expiry_date: Optional[datetime] = None


class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    interval_minutes: int
    tags: list[str]
    last_check: Optional[CheckSummary] = None


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    checked_at: datetime
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    is_timeout: bool
    error_message: Optional[str] = None
    dns_result: Optional[dict] = None
    redirect_result: Optional[dict] = None
    tls_result: Optional[dict] = None
    headers_result: Optional[dict] = None
    cert_expiry_date: Optional[datetime] = None
    score: Optional[int] = None
    letter_grade: Optional[str] = None
    score_reasons: Optional[list[str]] = None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    target_name: str
    alert_type: str
    message: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
