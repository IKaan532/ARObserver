from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(500), unique=True)
    interval_minutes: Mapped[int] = mapped_column(default=5)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_keyword: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    expected_status: Mapped[int] = mapped_column(default=200)
    active: Mapped[bool] = mapped_column(default=True)
    baseline_fingerprint: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    deep_check_result: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    deep_check_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    checks: Mapped[list["Check"]] = relationship(back_populates="target", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="target", cascade="all, delete-orphan")


class Check(Base):
    __tablename__ = "checks"
    __table_args__ = (
        Index(
            "ix_checks_target_id_checked_at_covering",
            "target_id",
            "checked_at",
            "status_code",
            "response_time_ms",
            "score",
        ),
        Index("ix_checks_checked_at_target_id_score", "checked_at", "target_id", "score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id"), index=True)
    checked_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)

    status_code: Mapped[Optional[int]] = mapped_column(default=None)
    response_time_ms: Mapped[Optional[float]] = mapped_column(default=None)
    is_timeout: Mapped[bool] = mapped_column(default=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), default=None)

    dns_result: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    redirect_result: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    tls_result: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    headers_result: Mapped[Optional[dict]] = mapped_column(JSON, default=None)

    cert_expiry_date: Mapped[Optional[datetime]] = mapped_column(default=None)

    score: Mapped[Optional[int]] = mapped_column(default=None)
    letter_grade: Mapped[Optional[str]] = mapped_column(String(1), default=None)
    score_reasons: Mapped[Optional[list[str]]] = mapped_column(JSON, default=None)

    content_result: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    timing_result: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    scoring_version: Mapped[Optional[int]] = mapped_column(default=None)

    target: Mapped["Target"] = relationship(back_populates="checks")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(default=None)

    target: Mapped["Target"] = relationship(back_populates="alerts")
