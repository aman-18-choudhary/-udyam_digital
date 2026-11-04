"""Order lifecycle and the real-time tracker.

Statuses move forward on a timer (DEMO_STEP_SECONDS) to stand in for the activation back-office.
Every transition is persisted as an OrderEvent, so the tracker survives a server restart.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from .config import DEMO_STEP_SECONDS, TODAY
from .db import Order, OrderEvent, SessionLocal, iso

log = logging.getLogger("udyam.orders")

PIPELINE = [
    ("PAYMENT_CONFIRMED", "Payment received. Thank you!"),
    ("KYC_VERIFIED", "Your documents are verified."),
    ("INSTALL_SCHEDULED", "Installation is scheduled for {date}. A technician will call you the day before."),
    ("INSTALLING", "Our technician is at your site."),
    ("ACTIVATED", "Your services are live. Welcome to Accel Business!"),
]
LABELS = {
    "PAYMENT_PENDING": "Waiting for payment", "PAYMENT_FAILED": "Payment failed, please retry",
    "PAYMENT_CONFIRMED": "Payment received", "KYC_VERIFIED": "Documents verified",
    "KYC_REVIEW": "Quick manual check", "INSTALL_SCHEDULED": "Installation scheduled",
    "INSTALLING": "Installing", "ACTIVATED": "Live",
}
_running: dict[str, asyncio.Task] = {}


def add_event(db, order: Order, status: str, note: str = "") -> None:
    order.status = status
    db.add(OrderEvent(order_id=order.id, status=status, note=note))


def install_date(order: Order):
    return TODAY + timedelta(days=int(order.quote.get("install_days", 3)))


def serialise(order: Order) -> dict:
    return {
        "id": order.id, "status": order.status, "label": LABELS.get(order.status, order.status),
        "business_name": order.business_name, "created_at": iso(order.created_at),
        "monthly_total": order.quote.get("monthly_total"), "first_payment": order.quote.get("first_payment"),
        "install_by": install_date(order).isoformat(),
        "lines": order.quote.get("lines", []),
        "steps": [s for s, _ in PIPELINE],
        "events": [{"id": e.id, "status": e.status, "label": LABELS.get(e.status, e.status), "note": e.note,
                    "at": iso(e.at)} for e in order.events],
    }


class CannotAdvance(Exception):
    pass


def next_step(order: Order):
    done = {e.status for e in order.events}
    return next((p for p in PIPELINE if p[0] not in done), None)


def advance(db, order: Order, kyc_status: str) -> str:
    """Move an order one step forward. Used by staff (ops) and by the demo timer."""
    if order.status in ("PAYMENT_PENDING", "PAYMENT_FAILED"):
        raise CannotAdvance("Payment has not been received yet.")
    nxt = next_step(order)
    if nxt is None:
        raise CannotAdvance("Order is already complete.")
    status, note = nxt
    if status == "KYC_VERIFIED" and kyc_status == "review":
        raise CannotAdvance("The KYC manual review for this order is still pending.")
    add_event(db, order, status, note.format(date=install_date(order).strftime("%d %b %Y")))
    return status


async def progress(order_id: str) -> None:
    """DEMO_MODE only: advance an order on a timer, standing in for the field back office."""
    from .db import KycCase
    try:
        while True:
            await asyncio.sleep(DEMO_STEP_SECONDS)
            with SessionLocal() as db:
                order = db.get(Order, order_id)
                if order is None or order.status in ("ACTIVATED", "PAYMENT_PENDING", "PAYMENT_FAILED"):
                    return
                try:
                    status = advance(db, order, "verified")  # the demo auto-approves manual review
                except CannotAdvance:
                    return
                db.commit()
                if status == "ACTIVATED":
                    return
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("order progress failed for %s", order_id)


_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Remember the server's event loop so sync (thread-pool) endpoints can start the demo timer too."""
    global _loop
    _loop = loop


def start(order_id: str) -> None:
    t = _running.get(order_id)
    if t and not t.done():
        return
    try:
        _running[order_id] = asyncio.get_running_loop().create_task(progress(order_id))
    except RuntimeError:  # called from a worker thread
        if _loop is not None:
            asyncio.run_coroutine_threadsafe(progress(order_id), _loop)


def resume_all() -> None:
    """Called on startup so orders mid-flight keep moving after a restart."""
    with SessionLocal() as db:
        ids = db.scalars(select(Order.id).where(Order.status.in_(
            ["PAYMENT_CONFIRMED", "KYC_VERIFIED", "KYC_REVIEW", "INSTALL_SCHEDULED", "INSTALLING"]))).all()
    for oid in ids:
        start(oid)
