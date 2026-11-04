"""Scheduled jobs. Usage: python -m app.jobs purge"""
from __future__ import annotations

import logging
import sys

from sqlalchemy import select

from .db import KycCase, SessionLocal, audit, now
from .storage import StorageError, get_storage

log = logging.getLogger("udyam.jobs")


def purge_expired() -> int:
    """Delete documents of rejected or abandoned KYC cases past their retention date."""
    n = 0
    with SessionLocal() as db:
        rows = db.scalars(select(KycCase).where(KycCase.delete_after.is_not(None), KycCase.delete_after <= now(),
                                                KycCase.status != "purged")).all()
        for case in rows:
            try:
                get_storage().delete(list((case.files or {}).values()))
            except StorageError:
                log.error("purge skipped for %s: storage unavailable", case.id)
                continue
            case.docs, case.files, case.status = {}, {}, "purged"
            audit(db, case.session_id, "documents_deleted", "system", case=case.id, reason="retention_expired")
            n += 1
        db.commit()
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ["purge"]:
        print(f"purged {purge_expired()} case(s)")
    else:
        sys.exit("usage: python -m app.jobs purge")
