"""Persistence (SQLAlchemy). Runs on SQLite by default and on Postgres via DATABASE_URL."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import AUTO_CREATE_TABLES, DATABASE_URL, IS_POSTGRES


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    """ISO string that always carries a UTC marker (SQLite returns naive datetimes)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("s"))
    user_id: Mapped[str] = mapped_column(String, index=True, default="")  # Clerk user id (owner)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    language: Mapped[str] = mapped_column(String, default="en")
    step: Mapped[str] = mapped_column(String, default="business_type")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)   # collected slots (no identifiers)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)     # term, business name, etc.


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("c"))
    session_id: Mapped[str] = mapped_column(String, index=True)
    purpose: Mapped[str] = mapped_column(String)
    notice_version: Mapped[str] = mapped_column(String)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KycCase(Base):
    __tablename__ = "kyc_cases"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("k"))
    session_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    claimed_gstin_masked: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")  # open|verified|review|action_required|purged
    docs: Mapped[dict] = mapped_column(JSON, default=dict)       # doc_type -> masked extract result
    files: Mapped[dict] = mapped_column(JSON, default=dict)      # doc_type -> stored path
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    gst_valid_for_sale: Mapped[int] = mapped_column(Integer, default=0)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("o"))
    session_id: Mapped[str] = mapped_column(String, index=True)
    kyc_case_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str] = mapped_column(String, default="PAYMENT_PENDING")
    items: Mapped[list] = mapped_column(JSON, default=list)
    quote: Mapped[dict] = mapped_column(JSON, default=dict)
    business_name: Mapped[str] = mapped_column(String, default="")
    payment_provider: Mapped[str] = mapped_column(String, default="test")
    payment_ref: Mapped[str | None] = mapped_column(String, nullable=True, index=True)   # Razorpay order id
    payment_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)   # one payment, one order
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    events: Mapped[list["OrderEvent"]] = relationship(back_populates="order", order_by="OrderEvent.id")


class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(String, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    order: Mapped[Order] = relationship(back_populates="events")


class AuditLog(Base):
    """Append-only trail of privacy relevant actions. Identifiers are always masked."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    session_id: Mapped[str] = mapped_column(String, index=True, default="")
    user_id: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


def _engine_kwargs() -> dict:
    if not IS_POSTGRES:
        return {"connect_args": {"check_same_thread": False}}
    kw: dict = {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 5, "pool_recycle": 1800}
    if ":6543/" in DATABASE_URL:  # Supabase transaction pooler does not support prepared statements
        kw["connect_args"] = {"prepare_threshold": None}
    return kw


engine = create_engine(DATABASE_URL, future=True, **_engine_kwargs())
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    """SQLite and tests create tables directly. Postgres uses `alembic upgrade head`."""
    if AUTO_CREATE_TABLES:
        Base.metadata.create_all(engine)


def audit(db, session_id: str, action: str, user_id: str = "", **detail) -> None:
    db.add(AuditLog(session_id=session_id, user_id=user_id, action=action, detail=detail))
