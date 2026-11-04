"""FastAPI application: advisor, quote, Smart KYC, orders with a live tracker, staff review and the sales console."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
from pathlib import Path
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from . import config, llm, orders, payments, propensity
from .advisor import (build_recommendation, handle as advisor_handle, opening as advisor_opening, to_profile)
from .auth import User, current_user, require_roles, require_staff
from .config import DATA_DIR, KYC_RETENTION_DAYS_REJECTED
from .crypto import decrypt_bytes, decrypt_json, encrypt_bytes, encrypt_json, selfcheck
from .data import catalogue
from .db import (AuditLog, ChatSession, Consent, KycCase, Order, SessionLocal, audit, init_db, iso, now, engine)
from .kyc import DOC_TYPES, extract, validate
from .registry import gstin_is_valid, lookup_gstin, lookup_udyam, mask, normalise_udyam
from .rules import Profile, eligibility, quote, validate_bundle
from .storage import StorageError, get_storage

logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("udyam.api")

LANGS = ["en", "hi", "mr", "ta", "te", "bn", "gu", "kn", "ml", "pa"]
MAX_UPLOAD = 8 * 1024 * 1024
NOTICE_VERSION = "2026-07-v1"
CONSENT_NOTICE = {
    "version": NOTICE_VERSION,
    "title": "Your documents, your choice",
    "purpose": "We use your GST certificate, Udyam certificate, signatory ID and address proof only to verify your "
               "business and set up your Accel Business services.",
    "collected": ["GST certificate", "Udyam certificate", "Signatory ID card", "Address proof (utility bill)"],
    "not_used_for": "Marketing, profiling or sharing with anyone outside Accel and its installation partners.",
    "protection": "Encrypted on upload and at rest. ID numbers are masked on screen and in logs. "
                  "Documents are never sent to an AI model; only your business type and size are.",
    "retention": f"If verification is not completed, your documents are deleted automatically after "
                 f"{KYC_RETENTION_DAYS_REJECTED} days. Verified customers' records are kept for the period "
                 "regulators require, then deleted.",
    "rights": "You can withdraw consent and have your documents deleted at any time from this screen.",
}


# ---------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if not config.AUTH_REQUIRED:
        log.warning("AUTH IS OFF: CLERK_ISSUER is not set, every request runs as a local admin. Dev only.")
    orders.set_loop(asyncio.get_running_loop())
    if config.DEMO_MODE:
        orders.resume_all()
    yield


app = FastAPI(title="Project Udyam Digital", version="2.0", lifespan=lifespan,
              docs_url="/api/docs" if not config.AUTH_REQUIRED else None, redoc_url=None,
              openapi_url="/api/openapi.json" if not config.AUTH_REQUIRED else None)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"],
                   allow_headers=["authorization", "content-type", "last-event-id"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    rid = uuid.uuid4().hex[:8]
    request.state.rid = rid
    t0 = time.perf_counter()
    resp = await call_next(request)
    resp.headers["x-request-id"] = rid
    resp.headers["x-content-type-options"] = "nosniff"
    resp.headers["referrer-policy"] = "no-referrer"
    if request.url.path.startswith("/api/") and "cache-control" not in resp.headers:
        resp.headers["cache-control"] = "no-store"
    log.info("%s %s %s %dms rid=%s", request.method, request.url.path, resp.status_code,
             (time.perf_counter() - t0) * 1000, rid)
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Log the real error server side; the customer gets a short message and a reference to quote."""
    rid = getattr(request.state, "rid", uuid.uuid4().hex[:8])
    log.error("unhandled %s on %s %s rid=%s", type(exc).__name__, request.method, request.url.path, rid,
              exc_info=exc)
    return JSONResponse({"detail": f"Something went wrong on our side. Please try again. Reference: {rid}"},
                        status_code=500)


_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def limit(name: str, n: int, per: int = 60):
    def dep(request: Request):
        ip = request.client.host if request.client else "?"
        q = _hits[(name, ip)]
        t = time.time()
        while q and q[0] < t - per:
            q.popleft()
        if len(q) >= n:
            raise HTTPException(429, "Too many requests, please slow down a little.")
        q.append(t)
    return dep


def db_dep():
    with SessionLocal() as db:
        yield db


# ---------------------------------------------------------------- ownership helpers
def get_session(db, sid: str, user: User) -> ChatSession:
    s = db.get(ChatSession, sid)
    if not s or s.user_id != user.id:  # same answer for "missing" and "not yours"
        raise HTTPException(404, "Unknown session")
    return s


def own_case(db, cid: str, user: User) -> KycCase:
    case = db.get(KycCase, cid)
    if not case or case.status == "purged":
        raise HTTPException(404, "Unknown or deleted KYC case")
    s = db.get(ChatSession, case.session_id)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Unknown or deleted KYC case")
    return case


def own_order(db, oid: str, user: User) -> Order:
    o = db.get(Order, oid)
    s = db.get(ChatSession, o.session_id) if o else None
    if not o or (not user.is_staff and (not s or s.user_id != user.id)):
        raise HTTPException(404, "Unknown order")
    return o


def profile_of(s: ChatSession, db, case_id: str | None = None) -> Profile:
    d = dict(s.profile or {})
    if case_id:
        case = db.get(KycCase, case_id)
        if case and case.session_id == s.id:
            # once documents exist, GST products depend on what the documents prove, not on what was typed
            d["has_valid_gstin"] = bool(case.gst_valid_for_sale)
    return to_profile(d)


# ---------------------------------------------------------------- meta
@app.get("/api/health")
def health(deep: bool = False):
    """Shallow by default (cheap enough for a platform health check). `?deep=1` also writes, reads and deletes a
    probe object in document storage, which is the quickest way to check Supabase keys and the bucket."""
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        db_ok = True
    except Exception:
        db_ok = False
    enc = selfcheck()
    body = {"db": "up" if db_ok else "down", "encryption": enc, "llm": llm.status(), "storage": get_storage().name,
            "payments": payments.provider(), "auth": "clerk" if config.AUTH_REQUIRED else "off"}
    ok = db_ok and enc == "ok"
    if deep:
        try:
            st = get_storage()
            st.put("_health/probe.bin", b"ok")
            good = st.get("_health/probe.bin") == b"ok"
            st.delete(["_health/probe.bin"])
            body["storage_read_write"] = "ok" if good else "mismatch"
        except Exception as e:
            body["storage_read_write"] = f"failed ({type(e).__name__})"
        ok = ok and body["storage_read_write"] == "ok"
    body["ok"] = ok
    return Response(json.dumps(body), status_code=200 if ok else 503, media_type="application/json")


@app.get("/api/config")
def get_config():
    return {"languages": LANGS, "llm": llm.status(), "today": config.TODAY.isoformat(),
            "consent_version": NOTICE_VERSION, "document_types": DOC_TYPES, "demo": config.DEMO_MODE,
            "auth_required": config.AUTH_REQUIRED,
            "payments": {"provider": payments.provider(),
                         "key_id": config.RAZORPAY_KEY_ID if payments.provider() == "razorpay" else None}}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "role": user.role, "staff": user.is_staff, "dev": user.dev}


# ---------------------------------------------------------------- advisor
class StartIn(BaseModel):
    language: str = "en"


class MessageIn(BaseModel):
    session_id: str
    text: str = Field(max_length=500)


@app.post("/api/advisor/start", dependencies=[Depends(limit("start", 30))])
def advisor_start(body: StartIn, db=Depends(db_dep), user: User = Depends(current_user)):
    lang = body.language if body.language in LANGS else "en"
    s = ChatSession(language=lang, user_id=user.id)
    db.add(s)
    db.commit()
    return {"session_id": s.id, **advisor_opening(lang)}


@app.post("/api/advisor/message", dependencies=[Depends(limit("advisor", 40))])
def advisor_message(body: MessageIn, db=Depends(db_dep), user: User = Depends(current_user)):
    s = get_session(db, body.session_id, user)
    resp = advisor_handle(s, body.text)
    if resp.get("action") == "handoff":
        audit(db, s.id, "handoff_requested", user.id, profile={k: v for k, v in s.profile.items() if k != "wants"})
    db.commit()
    return {"session_id": s.id, **resp}


@app.get("/api/advisor/session/{sid}")
def advisor_session(sid: str, db=Depends(db_dep), user: User = Depends(current_user)):
    s = get_session(db, sid, user)
    rec = build_recommendation(s.profile, s.extra.get("term", 12)) if s.step == "done" else None
    return {"session_id": s.id, "step": s.step, "profile": s.profile, "language": s.language,
            "business_name": s.extra.get("trade_name"), "recommendation": rec}


# ---------------------------------------------------------------- catalogue and quote
@app.get("/api/catalogue")
def get_catalogue(session_id: str | None = None, db=Depends(db_dep), user: User = Depends(current_user)):
    prof = profile_of(get_session(db, session_id, user), db) if session_id else None
    out = []
    for p in catalogue().values():
        row = {"id": p.id, "name": p.name, "category": p.category, "description": p.description, "unit": p.unit,
               "price_min": p.price_min, "price_max": p.price_max, "setup": p.setup,
               "min_contract": p.min_contract, "install_days": p.install_days}
        if prof:
            ok, reasons = eligibility(p, prof)
            row.update(eligible_standalone=ok, reasons=reasons)
        out.append(row)
    return out


class ItemIn(BaseModel):
    product_id: str
    qty: int = Field(ge=0, le=500)
    included: bool = True


class QuoteIn(BaseModel):
    session_id: str
    items: list[ItemIn]
    term: int = 12
    kyc_case_id: str | None = None


@app.post("/api/quote")
def make_quote(body: QuoteIn, db=Depends(db_dep), user: User = Depends(current_user)):
    if body.term not in (12, 24):
        raise HTTPException(422, "term must be 12 or 24 months")
    s = get_session(db, body.session_id, user)
    prof = profile_of(s, db, body.kyc_case_id)
    items = [i.model_dump() for i in body.items]
    problems = validate_bundle(items, prof)
    if problems:
        return {"ok": False, "problems": problems, "quote": None}
    return {"ok": True, "problems": [], "quote": quote(items, prof, body.term)}


# ---------------------------------------------------------------- consent
@app.get("/api/consent/notice")
def consent_notice():
    return CONSENT_NOTICE


class ConsentIn(BaseModel):
    session_id: str
    accept: bool
    notice_version: str


def _active_consent(db, sid: str) -> Consent | None:
    return db.scalar(select(Consent).where(Consent.session_id == sid, Consent.purpose == "kyc_verification",
                                           Consent.withdrawn_at.is_(None)))


@app.post("/api/consent")
def give_consent(body: ConsentIn, db=Depends(db_dep), user: User = Depends(current_user)):
    get_session(db, body.session_id, user)
    if not body.accept:
        raise HTTPException(422, "Consent is required to verify documents. You can also visit a partner store.")
    if body.notice_version != NOTICE_VERSION:
        raise HTTPException(409, "Consent notice has changed, please reload.")
    if not _active_consent(db, body.session_id):
        db.add(Consent(session_id=body.session_id, purpose="kyc_verification", notice_version=NOTICE_VERSION))
        audit(db, body.session_id, "consent_granted", user.id, purpose="kyc_verification", version=NOTICE_VERSION)
        db.commit()
    return {"ok": True}


def _purge_case(db, case: KycCase, reason: str, user_id: str = "") -> None:
    keys = list((case.files or {}).values())
    try:
        get_storage().delete(keys)
    except StorageError:
        log.error("could not delete stored documents for case %s", case.id)
        raise HTTPException(502, "Could not delete the stored documents right now. Nothing was changed; try again.")
    case.docs, case.files, case.status = {}, {}, "purged"
    audit(db, case.session_id, "documents_deleted", user_id, case=case.id, reason=reason)


@app.delete("/api/consent/{sid}")
def withdraw_consent(sid: str, db=Depends(db_dep), user: User = Depends(current_user)):
    get_session(db, sid, user)
    c = _active_consent(db, sid)
    if not c:
        raise HTTPException(404, "No active consent")
    cases = db.scalars(select(KycCase).where(KycCase.session_id == sid, KycCase.status != "purged")).all()
    for case in cases:
        _purge_case(db, case, "consent_withdrawn", user.id)
    c.withdrawn_at = now()
    audit(db, sid, "consent_withdrawn", user.id, purpose="kyc_verification")
    db.commit()
    return {"ok": True, "documents_deleted": len(cases)}


# ---------------------------------------------------------------- KYC
class LookupIn(BaseModel):
    gstin: str | None = None
    udyam: str | None = None


@app.post("/api/kyc/lookup", dependencies=[Depends(limit("lookup", 30))])
def kyc_lookup(body: LookupIn, user: User = Depends(current_user)):
    out: dict = {}
    if body.gstin:
        g = body.gstin.strip().upper()
        valid = gstin_is_valid(g)
        row = lookup_gstin(g) if valid else None
        out["gstin"] = {"masked": mask(g), "valid_format": valid, "found": bool(row),
                        "status": row["status"] if row else None,
                        "trade_name": row["trade_name"] if row else None,
                        "constitution": row["constitution"] if row else None,
                        "state": row["state"] if row else None}
    if body.udyam:
        u = normalise_udyam(body.udyam) or body.udyam.strip().upper()
        row = lookup_udyam(u)
        out["udyam"] = {"masked": mask(u), "found": bool(row),
                        "enterprise_name": row["enterprise_name"] if row else None,
                        "enterprise_type": row["enterprise_type"] if row else None,
                        "state": row["state"] if row else None}
    if not out:
        raise HTTPException(422, "Provide a gstin or a udyam number")
    return out


class CaseIn(BaseModel):
    session_id: str
    gstin: str | None = None


def _blob(case: KycCase) -> dict:
    tok = (case.docs or {}).get("enc")
    return decrypt_json(tok) if tok else {"docs": {}, "claimed_gstin": None}


def _save_blob(case: KycCase, blob: dict) -> None:
    case.docs = {"enc": encrypt_json(blob)}


def _masked_fields(f: dict) -> dict:
    out = dict(f)
    for k in ("gstin", "udyam_number"):
        if out.get(k):
            out[k] = mask(out[k])
    out.pop("gstin_raw_ocr", None)
    return out


def _masked_doc(d: dict) -> dict:
    return {"doc_type": d["doc_type"], "label": DOC_TYPES.get(d["doc_type"], d["doc_type"]),
            "fields": _masked_fields(d["fields"]), "issues": d["issues"], "quality": d["quality"]}


def _case_view(case: KycCase) -> dict:
    blob = _blob(case) if case.status != "purged" else {"docs": {}}
    return {"id": case.id, "status": case.status, "documents": {k: _masked_doc(v) for k, v in blob["docs"].items()},
            "result": case.result or None, "delete_after": iso(case.delete_after)}


@app.post("/api/kyc/cases", dependencies=[Depends(limit("case", 20))])
def create_case(body: CaseIn, db=Depends(db_dep), user: User = Depends(current_user)):
    get_session(db, body.session_id, user)
    if not _active_consent(db, body.session_id):
        raise HTTPException(403, "Consent is required before documents can be collected.")
    case = KycCase(session_id=body.session_id,
                   claimed_gstin_masked=mask(body.gstin.upper()) if body.gstin else None,
                   delete_after=now() + timedelta(days=KYC_RETENTION_DAYS_REJECTED))
    _save_blob(case, {"docs": {}, "claimed_gstin": body.gstin.upper() if body.gstin else None})
    db.add(case)
    audit(db, body.session_id, "kyc_case_opened", user.id, case=case.id)
    db.commit()
    return _case_view(case)


def _ingest(db, case: KycCase, data: bytes, doc_type: str | None, user_id: str) -> dict:
    if doc_type is not None and doc_type not in DOC_TYPES:
        raise HTTPException(422, f"doc_type must be one of {list(DOC_TYPES)}")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 8 MB")
    try:
        Image.open(io.BytesIO(data)).verify()
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(422, "That file is not a readable image (use PNG or JPG).")
    res = extract(img, forced_type=doc_type)
    if res["doc_type"] is None:
        return {"stored": False, "document": {"doc_type": None, "issues": res["issues"], "quality": res["quality"],
                                                "fields": {}, "label": "Unrecognised"}}
    key = f"{case.id}/{res['doc_type']}.bin"
    try:
        get_storage().put(key, encrypt_bytes(data))
    except StorageError:
        raise HTTPException(502, "Could not store the document right now. Please try again.")
    blob = _blob(case)
    blob["docs"][res["doc_type"]] = res
    _save_blob(case, blob)
    case.files = {**(case.files or {}), res["doc_type"]: key}
    case.status, case.result = "open", {}
    audit(db, case.session_id, "document_received", user_id, case=case.id, doc=res["doc_type"])
    db.commit()
    return {"stored": True, "document": _masked_doc(res)}


@app.post("/api/kyc/cases/{cid}/documents", dependencies=[Depends(limit("upload", 30))])
async def upload_document(cid: str, file: UploadFile = File(...), doc_type: str | None = Form(None),
                          db=Depends(db_dep), user: User = Depends(current_user)):
    case = own_case(db, cid, user)
    if not _active_consent(db, case.session_id):
        raise HTTPException(403, "Consent has been withdrawn.")
    data = await file.read(MAX_UPLOAD + 1)
    return await asyncio.to_thread(_ingest, db, case, data, doc_type or None, user.id)


# ---- demo helpers (sample applicants from the case pack). Disabled unless DEMO_MODE=true.
def _demo_only():
    if not config.DEMO_MODE:
        raise HTTPException(404, "Not found")


@app.get("/api/kyc/specimens")
def specimens():
    _demo_only()
    out = []
    for n in range(1, 13):
        k = f"K{n:02d}"
        files = sorted((DATA_DIR / "kyc_documents").glob(f"{k}_*.png"))
        out.append({"id": k, "documents": [f.stem[4:] for f in files]})
    return out


class SpecimenIn(BaseModel):
    applicant: str


@app.post("/api/kyc/cases/{cid}/specimen", dependencies=[Depends(limit("specimen", 20))])
async def load_specimen(cid: str, body: SpecimenIn, db=Depends(db_dep), user: User = Depends(current_user)):
    _demo_only()
    if not re.fullmatch(r"K(0[1-9]|1[0-2])", body.applicant):
        raise HTTPException(422, "applicant must be K01..K12")
    case = own_case(db, cid, user)
    hint = {"gst_certificate": "gst", "udyam_certificate": "udyam", "signatory_id": "id", "address_proof": "address"}
    out = []
    for f in sorted((DATA_DIR / "kyc_documents").glob(f"{body.applicant}_*.png")):
        dt = hint[f.stem[4:]]
        out.append((await asyncio.to_thread(_ingest, db, case, f.read_bytes(), dt, user.id))["document"])
    return {"documents": out, "case": _case_view(case)}


@app.post("/api/kyc/cases/{cid}/verify")
async def verify_case(cid: str, db=Depends(db_dep), user: User = Depends(current_user)):
    case = own_case(db, cid, user)
    if not _active_consent(db, case.session_id):
        raise HTTPException(403, "Consent has been withdrawn.")
    blob = _blob(case)
    result = await asyncio.to_thread(validate, blob["docs"], blob.get("claimed_gstin"))
    case.result = result
    case.status = result["decision"]
    case.gst_valid_for_sale = int(result["gst_valid_for_sale"])
    case.delete_after = None if result["decision"] in ("verified", "review") else now() + timedelta(
        days=KYC_RETENTION_DAYS_REJECTED)
    audit(db, case.session_id, "kyc_decision", user.id, case=case.id, decision=result["decision"],
          summary=result["summary"])
    db.commit()
    return _case_view(case)


@app.get("/api/kyc/cases/{cid}")
def get_case(cid: str, db=Depends(db_dep), user: User = Depends(current_user)):
    return _case_view(own_case(db, cid, user))


@app.post("/api/admin/purge")
def purge_expired(db=Depends(db_dep), user: User = Depends(require_roles("ops"))):
    """Retention job. In production also run it on a schedule (see docs/SETUP_PRODUCTION.md)."""
    rows = db.scalars(select(KycCase).where(KycCase.delete_after.is_not(None), KycCase.delete_after <= now(),
                                            KycCase.status != "purged")).all()
    for c in rows:
        _purge_case(db, c, "retention_expired", user.id)
    db.commit()
    return {"purged": len(rows)}


# ---------------------------------------------------------------- orders
class OrderIn(BaseModel):
    session_id: str
    kyc_case_id: str
    items: list[ItemIn]
    term: int = 12


@app.post("/api/orders")
def create_order(body: OrderIn, db=Depends(db_dep), user: User = Depends(current_user)):
    s = get_session(db, body.session_id, user)
    case = own_case(db, body.kyc_case_id, user)
    if case.session_id != s.id:
        raise HTTPException(403, "KYC case belongs to another session")
    if case.status not in ("verified", "review"):
        raise HTTPException(409, "KYC must be verified before an order can be placed.")
    if body.term not in (12, 24):
        raise HTTPException(422, "term must be 12 or 24 months")
    prof = profile_of(s, db, case.id)
    items = [i.model_dump() for i in body.items]
    problems = validate_bundle(items, prof)
    if problems:
        raise HTTPException(422, {"problems": problems})
    q = quote(items, prof, body.term)  # price is always recomputed on the server
    blob = _blob(case)["docs"]
    name = (blob.get("gst", {}).get("fields", {}).get("trade_name")
            or blob.get("udyam", {}).get("fields", {}).get("enterprise_name") or s.extra.get("trade_name") or "")
    # One unpaid order per KYC case: going Back and forward must not pile up duplicates. The bundle is refreshed,
    # and a Razorpay order created for a different amount is dropped so the customer is never charged a stale price.
    o = db.scalar(select(Order).where(Order.kyc_case_id == case.id, Order.status.in_(("PAYMENT_PENDING", "PAYMENT_FAILED")))
                  .order_by(Order.created_at.desc()))
    if o:
        if o.quote.get("first_payment") != q["first_payment"]:
            o.payment_ref = None
        o.items, o.quote, o.business_name = items, q, name
        db.commit()
        return orders.serialise(o)
    o = Order(session_id=s.id, kyc_case_id=case.id, items=items, quote=q, business_name=name)
    db.add(o)
    db.flush()
    orders.add_event(db, o, "PAYMENT_PENDING", f"Order placed. First payment: ₹{q['first_payment']:,}.")
    audit(db, s.id, "order_created", user.id, order=o.id, monthly=q["monthly_total"])
    db.commit()
    return orders.serialise(o)


@app.get("/api/my/orders")
def my_orders(db=Depends(db_dep), user: User = Depends(current_user)):
    rows = db.scalars(select(Order).join(ChatSession, ChatSession.id == Order.session_id)
                      .where(ChatSession.user_id == user.id).order_by(Order.created_at.desc()).limit(20)).all()
    return [orders.serialise(o) for o in rows]


class PayIn(BaseModel):
    method: str = "upi"
    simulate_failure: bool = False


def _mark_paid(db, o: Order, payment_id: str, method: str, user_id: str = "") -> bool:
    """Record a confirmed payment exactly once (safe to call from the browser path and the webhook)."""
    if o.status not in ("PAYMENT_PENDING", "PAYMENT_FAILED"):
        return False
    o.payment_id, o.paid_at = payment_id, now()
    orders.add_event(db, o, "PAYMENT_CONFIRMED", f"Payment of ₹{o.quote['first_payment']:,} received via {method}.")
    case = db.get(KycCase, o.kyc_case_id) if o.kyc_case_id else None
    if case and case.status == "review":
        orders.add_event(db, o, "KYC_REVIEW", "A reviewer is checking one item in your documents. "
                                              "We will continue as soon as it is done.")
    audit(db, o.session_id, "payment_confirmed", user_id, order=o.id, provider=o.payment_provider, method=method)
    return True


@app.post("/api/orders/{oid}/pay")
async def pay_order(oid: str, body: PayIn, db=Depends(db_dep), user: User = Depends(current_user)):
    """Test-mode payment for local development. Refused outright once a real gateway is configured."""
    if payments.provider() != "test":
        raise HTTPException(409, "Test payments are disabled. Use the online payment flow.")
    o = own_order(db, oid, user)
    if body.method not in ("upi", "card", "netbanking"):
        raise HTTPException(422, "Unsupported payment method")
    if o.status not in ("PAYMENT_PENDING", "PAYMENT_FAILED"):
        raise HTTPException(409, "This order has already been paid")
    if body.simulate_failure and config.DEMO_MODE:
        orders.add_event(db, o, "PAYMENT_FAILED", "The bank declined the payment (test mode). You can retry.")
        db.commit()
        return orders.serialise(o)
    _mark_paid(db, o, f"test_{uuid.uuid4().hex[:12]}", f"{body.method.upper()} (test mode)", user.id)
    db.commit()
    if config.DEMO_MODE:
        orders.start(o.id)
    return orders.serialise(o)


# ---- Razorpay
@app.post("/api/orders/{oid}/payment-intent", dependencies=[Depends(limit("intent", 20))])
def payment_intent(oid: str, db=Depends(db_dep), user: User = Depends(current_user)):
    if payments.provider() != "razorpay":
        raise HTTPException(409, "Online payments are not enabled on this server.")
    o = own_order(db, oid, user)
    if o.status not in ("PAYMENT_PENDING", "PAYMENT_FAILED"):
        raise HTTPException(409, "This order has already been paid")
    amount = int(o.quote["first_payment"])
    if not o.payment_ref:  # reuse the Razorpay order on retries so one order never has several open payments
        try:
            rz = payments.create_order(amount, o.id, {"order_id": o.id})
        except payments.PaymentError as e:
            raise HTTPException(502, str(e))
        o.payment_provider, o.payment_ref = "razorpay", rz["id"]
        audit(db, o.session_id, "payment_intent_created", user.id, order=o.id, amount=amount)
        db.commit()
    return {"provider": "razorpay", "key_id": config.RAZORPAY_KEY_ID, "razorpay_order_id": o.payment_ref,
            "amount_paise": amount * 100, "currency": "INR", "name": "Accel Business",
            "description": f"Order {o.id}"}


class VerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@app.post("/api/orders/{oid}/verify-payment", dependencies=[Depends(limit("verify", 30))])
def verify_payment(oid: str, body: VerifyIn, db=Depends(db_dep), user: User = Depends(current_user)):
    if payments.provider() != "razorpay":
        raise HTTPException(409, "Online payments are not enabled on this server.")
    o = own_order(db, oid, user)
    if o.status not in ("PAYMENT_PENDING", "PAYMENT_FAILED"):
        return orders.serialise(o)  # already confirmed (for example by the webhook): idempotent
    if not o.payment_ref or body.razorpay_order_id != o.payment_ref:
        raise HTTPException(400, "This payment does not belong to this order.")
    if not payments.verify_checkout_signature(body.razorpay_order_id, body.razorpay_payment_id,
                                              body.razorpay_signature):
        audit(db, o.session_id, "payment_signature_invalid", user.id, order=o.id)
        db.commit()
        raise HTTPException(400, "Payment could not be verified.")
    try:
        payment = payments.fetch_payment(body.razorpay_payment_id)
    except payments.PaymentError as e:
        raise HTTPException(502, str(e))
    ok, why = payments.payment_matches(payment, o.payment_ref, int(o.quote["first_payment"]))
    if not ok:
        audit(db, o.session_id, "payment_mismatch", user.id, order=o.id, reason=why)
        db.commit()
        raise HTTPException(400, "Payment could not be verified.")
    taken = db.scalar(select(Order.id).where(Order.payment_id == body.razorpay_payment_id, Order.id != o.id))
    if taken:
        raise HTTPException(409, "This payment was already used.")
    _mark_paid(db, o, body.razorpay_payment_id, (payment.get("method") or "online").upper(), user.id)
    db.commit()
    if config.DEMO_MODE:
        orders.start(o.id)
    return orders.serialise(o)


@app.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request, db=Depends(db_dep)):
    """Public endpoint, authenticated only by Razorpay's signature over the raw body."""
    raw = await request.body()
    if not payments.verify_webhook_signature(raw, request.headers.get("x-razorpay-signature", "")):
        raise HTTPException(400, "bad signature")
    try:
        event = json.loads(raw)
        etype = event["event"]
        entity = event["payload"]["payment"]["entity"]
    except (ValueError, KeyError, TypeError):
        return {"ok": True, "ignored": "unsupported payload"}
    o = db.scalar(select(Order).where(Order.payment_ref == entity.get("order_id")))
    if not o:
        log.warning("webhook for unknown razorpay order")
        return {"ok": True, "ignored": "unknown order"}  # 200 so Razorpay stops retrying
    if etype in ("payment.captured", "order.paid"):
        ok, why = payments.payment_matches(entity, o.payment_ref, int(o.quote["first_payment"]))
        if not ok:
            audit(db, o.session_id, "payment_mismatch", "webhook", order=o.id, reason=why)
        elif not db.scalar(select(Order.id).where(Order.payment_id == entity["id"], Order.id != o.id)):
            _mark_paid(db, o, entity["id"], (entity.get("method") or "online").upper(), "webhook")
    elif etype == "payment.failed" and o.status == "PAYMENT_PENDING":
        orders.add_event(db, o, "PAYMENT_FAILED", "The payment did not go through. You can try again.")
        audit(db, o.session_id, "payment_failed", "webhook", order=o.id)
    db.commit()
    if config.DEMO_MODE and o.status == "PAYMENT_CONFIRMED":
        orders.start(o.id)
    return {"ok": True}


@app.get("/api/orders/{oid}")
def get_order(oid: str, db=Depends(db_dep), user: User = Depends(current_user)):
    return orders.serialise(own_order(db, oid, user))


@app.get("/api/orders/{oid}/stream")
async def stream_order(oid: str, request: Request, user: User = Depends(current_user)):
    """Server-sent events: pushes each status change as soon as it is stored. Authenticated by header, so
    the browser client reads it with fetch() instead of EventSource."""
    with SessionLocal() as db:
        own_order(db, oid, user)
    last = int(request.headers.get("last-event-id", "0") or 0)

    async def gen():
        nonlocal last
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            with SessionLocal() as db:
                o = db.get(Order, oid)
                if not o:
                    yield "event: error\ndata: {\"error\":\"unknown order\"}\n\n"
                    return
                new = [e for e in o.events if e.id > last]
                for e in new:
                    last = e.id
                    yield f"id: {e.id}\nevent: order\ndata: {json.dumps(orders.serialise(o))}\n\n"
                    idle = 0
                if o.status == "ACTIVATED" and not new:
                    return
            idle += 1
            if idle % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- staff: sales console
@app.get("/api/backoffice/funnel")
def bo_funnel(user: User = Depends(require_staff)):
    return propensity.funnel()


@app.get("/api/backoffice/leads")
def bo_leads(limit_: int = Query(25, alias="limit", ge=1, le=200), min_stage: str = "Needs assessed",
             segment: str | None = None, user: User = Depends(require_staff)):
    if min_stage not in propensity.STAGE_ORDER:
        raise HTTPException(422, "unknown stage")
    return propensity.score_open_leads(limit_, min_stage, segment)


@app.get("/api/backoffice/model")
def bo_model(user: User = Depends(require_staff)):
    _, auc = propensity.model()
    return {"type": "smoothed naive Bayes on profile features + stage lift", "holdout_auc_profile_only": auc,
            "note": "Profile features alone are weakly predictive (AUC about 0.65); stage reached adds most of the signal."}


@app.get("/api/backoffice/handoffs")
def bo_handoffs(db=Depends(db_dep), user: User = Depends(require_staff)):
    rows = db.scalars(select(AuditLog).where(AuditLog.action == "handoff_requested")
                      .order_by(AuditLog.id.desc()).limit(50)).all()
    return [{"at": iso(r.at), "session_id": r.session_id, "profile": r.detail.get("profile")} for r in rows]


@app.get("/api/backoffice/orders")
def bo_orders(db=Depends(db_dep), user: User = Depends(require_staff)):
    rows = db.scalars(select(Order).order_by(Order.created_at.desc()).limit(50)).all()
    return [{"id": o.id, "business": o.business_name, "status": o.status, "monthly_total": o.quote.get("monthly_total"),
             "created_at": iso(o.created_at), "kyc_case_id": o.kyc_case_id,
             "can_advance": o.status not in ("PAYMENT_PENDING", "PAYMENT_FAILED", "ACTIVATED")} for o in rows]


# ---------------------------------------------------------------- staff: KYC review queue and order operations
@app.get("/api/ops/reviews")
def review_queue(db=Depends(db_dep), user: User = Depends(require_roles("ops", "sales"))):
    rows = db.scalars(select(KycCase).where(KycCase.status == "review").order_by(KycCase.created_at)).all()
    return [{"id": c.id, "created_at": iso(c.created_at), "documents": list((c.files or {}).keys()),
             "warnings": [x for x in (c.result or {}).get("checks", []) if x["status"] == "warn"]} for c in rows]


@app.get("/api/ops/reviews/{cid}/documents/{doc_type}")
def review_document(cid: str, doc_type: str, db=Depends(db_dep), user: User = Depends(require_roles("ops"))):
    case = db.get(KycCase, cid)
    key = (case.files or {}).get(doc_type) if case and case.status != "purged" else None
    if not key:
        raise HTTPException(404, "No such document")
    try:
        data = decrypt_bytes(get_storage().get(key))
    except StorageError:
        raise HTTPException(502, "Document store unavailable")
    audit(db, case.session_id, "document_viewed_by_staff", user.id, case=cid, doc=doc_type)
    db.commit()
    fmt = (Image.open(io.BytesIO(data)).format or "PNG").lower()
    return Response(data, media_type=f"image/{fmt}", headers={"cache-control": "no-store"})


class ReviewDecision(BaseModel):
    approve: bool
    note: str = Field("", max_length=300)


@app.post("/api/ops/reviews/{cid}/decision")
def review_decision(cid: str, body: ReviewDecision, db=Depends(db_dep), user: User = Depends(require_roles("ops"))):
    case = db.get(KycCase, cid)
    if not case or case.status != "review":
        raise HTTPException(404, "No pending review for this case")
    case.status = "verified" if body.approve else "action_required"
    audit(db, case.session_id, "kyc_review_decision", user.id, case=cid, approve=body.approve, note=body.note)
    db.commit()
    return {"id": cid, "status": case.status}


@app.post("/api/ops/orders/{oid}/advance")
def advance_order(oid: str, db=Depends(db_dep), user: User = Depends(require_roles("ops"))):
    o = db.get(Order, oid)
    if not o:
        raise HTTPException(404, "Unknown order")
    case = db.get(KycCase, o.kyc_case_id) if o.kyc_case_id else None
    try:
        status = orders.advance(db, o, case.status if case else "verified")
    except orders.CannotAdvance as e:
        raise HTTPException(409, str(e))
    audit(db, o.session_id, "order_advanced", user.id, order=oid, status=status)
    db.commit()
    return orders.serialise(o)


# ---------------------------------------------------------------- web app (single-origin deployment)
# When the built frontend is present (the Docker image ships it), the API serves it too. One origin means
# no CORS, and server-sent events reach the browser without an extra proxy hop.
_DIST = Path(os.getenv("WEB_DIST_DIR") or config.PROJECT_ROOT / "udyam" / "frontend" / "dist")
if (_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = (_DIST / path).resolve()
        if path and f.is_file() and _DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(_DIST / "index.html", headers={"cache-control": "no-cache"})
