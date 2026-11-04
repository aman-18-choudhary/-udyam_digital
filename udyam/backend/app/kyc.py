"""Smart KYC: OCR, field extraction and cross-document validation.

Nothing here talks to an LLM. Raw ID numbers and document images stay inside this module;
callers get masked values for logs and UI (see registry.mask).
"""
from __future__ import annotations

import re
from datetime import date, datetime

import numpy as np
import pytesseract
from PIL import Image, ImageOps
from rapidfuzz import fuzz

from .config import ADDRESS_PROOF_MAX_AGE_DAYS, TODAY
from .data import gstin_registry
from .registry import (STATE_CODES, UDYAM_STATE, UDYAM_RE, find_by_name, gstin_is_valid, lookup_gstin,
                       lookup_udyam, normalise_udyam, repair_gstin)

BLUR_MIN = 300.0  # Laplacian variance; sharp specimens score >1400, the blurred one scores ~9
AUTHORISED = {"owner", "proprietor", "partner", "director", "managing director", "authorised signatory"}
INDIAN_STATES = sorted({*STATE_CODES.values(), *UDYAM_STATE.values()}, key=len, reverse=True)

DOC_TYPES = {
    "gst": "GST certificate",
    "udyam": "Udyam certificate",
    "id": "Signatory ID",
    "address": "Address proof",
}


# ---------------------------------------------------------------- image preparation
def _blur_score(g: Image.Image) -> float:
    a = np.asarray(g.resize((620, max(1, int(620 * g.height / g.width)))), dtype=np.float32)
    lap = a[1:-1, 1:-1] * 4 - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return float(lap.var())


def _skew_angle(g: Image.Image) -> float:
    small = g.resize((600, max(1, int(600 * g.height / g.width))))
    mask = Image.fromarray(((np.asarray(small) < 110) * 255).astype("uint8"))
    best_ang, best = 0.0, -1.0
    for ang in np.arange(-12, 12.1, 1.0):
        rot = np.asarray(mask.rotate(float(ang), fillcolor=0)) > 0
        s = rot.sum(axis=1).astype(float).var()
        if s > best:
            best_ang, best = float(ang), s
    return best_ang


def prepare(path_or_image) -> tuple[Image.Image, dict]:
    im = path_or_image if isinstance(path_or_image, Image.Image) else Image.open(path_or_image)
    im = ImageOps.exif_transpose(im).convert("RGB")
    g = ImageOps.grayscale(im)
    blur, angle = _blur_score(g), _skew_angle(g)
    if abs(angle) >= 2:
        g = g.rotate(angle, expand=True, fillcolor=255, resample=Image.BICUBIC)
    g = g.resize((g.width * 3 // 2, g.height * 3 // 2), Image.LANCZOS)
    # Threshold removes the light pink watermark but keeps the dark text.
    g = g.point(lambda p: 255 if p > 120 else 0)
    return g, {"blur_score": round(blur, 1), "skew_deg": angle, "blurred": blur < BLUR_MIN,
               "deskewed": abs(angle) >= 2}


# ---------------------------------------------------------------- text helpers
def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\(\s*prop\.?\s*([^)]*)\)?", r" \1 ", s)
    s = s.replace("private limited", "pvt ltd").replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _prop_parts(legal: str) -> tuple[str, str]:
    """'Joseph Singh (Prop. Ganesh Woodcraft)' -> ('Joseph Singh', 'Ganesh Woodcraft')."""
    m = re.match(r"^(.*?)\s*\(\s*Prop\.?\s*(.*?)\)?\s*$", legal or "")
    return (m.group(1).strip(), m.group(2).strip().rstrip(")")) if m else ("", legal or "")


def _name_score(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(_norm(a), _norm(b))


def _join_wrapped(first: str, rest: str) -> str:
    first, rest = first.strip(), rest.strip()
    if not rest:
        return first
    if first.endswith(("-", ",")) or rest.startswith(("-", ",")):
        return f"{first} {rest}"
    return first + rest


def _addr_norm(a: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (a or "").lower())


def _pin(a: str) -> str | None:
    m = re.search(r"(\d{6})\s*$", (a or "").strip())
    return m.group(1) if m else None


def _state_of(address: str) -> str | None:
    for st in INDIAN_STATES:
        if st.lower() in (address or "").lower():
            return st
    return None


def _first_date(s: str) -> date | None:
    m = re.search(r"(\d{4})\s*-\s*(\d{2})\s*[-.]\s*(\d{2})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------- OCR
def _ocr_lines(img: Image.Image) -> list[str]:
    txt = pytesseract.image_to_string(img, config="--psm 6")
    out = []
    for ln in txt.splitlines():
        ln = ln.strip()
        up = ln.upper()
        if ln and "SPECIMEN -" not in up and "NOT A VALID" not in up and "SYNTHETIC" not in up \
                and "hackathon" not in ln.lower():
            out.append(ln)
    return out


def _classify(lines: list[str]) -> str | None:
    t = " ".join(lines).lower()
    if "gst registration" in t or "gstin" in t:
        return "gst"
    if "udyam registration" in t or "udyam reg" in t:
        return "udyam"
    if "signatory" in t or ("designation" in t and "id no" in t):
        return "id"
    if "electricity bill" in t or "utility" in t or "consumer no" in t:
        return "address"
    return None


def _after(lines: list[str], label: str) -> str | None:
    """Value on the same line after `label` (case-insensitive, tolerant of OCR noise in the label)."""
    pat = re.compile(rf"^\s*{label}(?:\s*:\s*|\s+)(.*)$", re.I)
    for ln in lines:
        m = pat.match(ln)
        if m:
            return m.group(1).strip()
    return None


def _value_below(lines: list[str], label: str) -> str | None:
    """Layouts where OCR puts the value on the following line."""
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*{label}\s*$", ln, re.I) and i + 1 < len(lines):
            return lines[i + 1].strip()
    return None


def _gstin_second_pass(img: Image.Image) -> str | None:
    """Re-read only the GSTIN value cell with a character whitelist at higher zoom."""
    try:
        d = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT)
    except Exception:
        return None
    for i, w in enumerate(d["text"]):
        if w.strip().upper().startswith("GSTIN"):
            x, y, h = d["left"][i] + d["width"][i], d["top"][i], d["height"][i]
            box = (x + 20, max(0, y - int(h * 0.6)), img.width, y + int(h * 1.8))
            crop = img.crop(box)
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
            cfg = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            return pytesseract.image_to_string(crop, config=cfg).strip() or None
    return None


def extract(path_or_image, forced_type: str | None = None) -> dict:
    """OCR one image and return {doc_type, fields, quality, issues}."""
    img, quality = prepare(path_or_image)
    lines = _ocr_lines(img)
    doc_type = forced_type or _classify(lines)
    res = {"doc_type": doc_type, "fields": {}, "quality": quality, "issues": [], "raw_lines": len(lines)}

    if quality["blurred"]:
        res["issues"].append({"code": "blurred", "message": "The image is too blurry to read reliably. "
                              "Please retake it in good light."})
    if doc_type is None:
        res["issues"].append({"code": "unrecognised", "message": "Could not recognise this document type."})
        return res

    f: dict = {}
    if doc_type == "gst":
        raw = _after(lines, "GSTIN") or ""
        g, how = repair_gstin(raw) if raw else (None, "missing")
        if g is None or how.startswith("registry-nearest(d=3"):
            alt = _gstin_second_pass(img)
            if alt:
                g2, how2 = repair_gstin(alt)
                if g2 and (g is None or how2 == "exact" or how2 == "ocr-char-fix"):
                    g, how = g2, how2 + "+crop"
        f["gstin"], f["gstin_method"] = g, how
        f["gstin_raw_ocr"] = raw
        f["legal_name"] = _after(lines, r"Legal n[a-z]*me")
        f["trade_name"] = _after(lines, r"Trade n[a-z]*me")
        f["constitution"] = _after(lines, "Constitution")
        a1 = _after(lines, r"Address of princip[a-z]*") or ""
        a2 = _after(lines, r"place of business") or ""
        f["address"] = _join_wrapped(a1, a2)
        f["liability_date"] = str(_first_date(_after(lines, r"Date of liability") or "") or "")
    elif doc_type == "udyam":
        raw = _after(lines, r"Udyam reg\.? number") or ""
        f["udyam_number"] = normalise_udyam(raw)
        f["enterprise_name"] = _after(lines, "Enterprise name")
        f["activity"] = _after(lines, "Major activity")
        f["city"] = _after(lines, "City")
        f["state"] = _after(lines, "State")
        f["registration_date"] = str(_first_date(_after(lines, r"Date of registration") or "") or "")
        if not f["udyam_number"]:
            res["issues"].append({"code": "field_missing", "message": "The Udyam registration number is "
                                  "missing from this certificate."})
    elif doc_type == "id":
        f["name"] = _value_below(lines, "Name") or _after(lines, "Name")
        f["designation"] = _value_below(lines, "Designation")
        f["business"] = _value_below(lines, r"For business")
        f["id_number_masked"] = None
        idn = _value_below(lines, r"ID no\.?")
        if idn:
            f["id_number_masked"] = "*" * max(0, len(idn) - 4) + idn[-4:]
        vt = _value_below(lines, r"Va[a-z]*d till")
        f["valid_till"] = str(_first_date(vt or "") or "")
    elif doc_type == "address":
        f["billed_to"] = _after(lines, "Billed to")
        s1 = _after(lines, "Supply address") or ""
        # the wrapped half of the address is the next line that is not a label
        nxt = ""
        for i, ln in enumerate(lines):
            if re.match(r"^\s*Supply address", ln, re.I) and i + 1 < len(lines):
                cand = lines[i + 1]
                if not re.match(r"^\s*(Bill date|Units|Amount|Consumer|Billed)", cand, re.I):
                    nxt = cand
                break
        f["address"] = _join_wrapped(s1, nxt)
        f["bill_date"] = str(_first_date(_after(lines, "Bill date") or "") or "")
        f["amount_due"] = _after(lines, r"Amount due.*")
    res["fields"] = f
    return res


# ---------------------------------------------------------------- cross-document validation
def _chk(cid: str, label: str, status: str, detail: str, fix: str = "") -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail, "fix": fix}


def validate(docs: dict[str, dict], claimed_gstin: str | None = None) -> dict:
    """`docs` maps doc_type -> extract() result. Returns checks and an overall decision."""
    checks: list[dict] = []
    def fields(k: str) -> dict:
        d = docs.get(k, {})
        # a blurred upload is reported once as unreadable; its half-read text is not used for other checks
        return {} if d.get("quality", {}).get("blurred") else d.get("fields", {})

    g, u, i, a = fields("gst"), fields("udyam"), fields("id"), fields("address")

    # 1. completeness
    have_reg = "gst" in docs or "udyam" in docs
    missing = [DOC_TYPES[k] for k in ("id", "address") if k not in docs]
    if not have_reg:
        missing.insert(0, "GST or Udyam certificate")
    if missing:
        checks.append(_chk("docs_present", "Required documents", "fail", "Missing: " + ", ".join(missing),
                           "Upload the missing document(s)."))
    else:
        note = "" if "udyam" in docs and "gst" in docs else " (the other registration is optional)"
        checks.append(_chk("docs_present", "Required documents", "pass", "All required documents received" + note))

    # 2. image quality
    for k, d in docs.items():
        for iss in d.get("issues", []):
            if iss["code"] == "field_missing":
                continue
            sev = "fail" if iss["code"] == "blurred" else "warn"
            checks.append(_chk(f"quality_{k}", f"{DOC_TYPES.get(k, k)} readability", sev, iss["message"],
                               "Re-upload a clear photo or scan."))
        if d.get("quality", {}).get("deskewed"):
            checks.append(_chk(f"deskew_{k}", f"{DOC_TYPES.get(k, k)} orientation", "info",
                               f"Photo was tilted {abs(d['quality']['skew_deg']):.0f} degrees; straightened automatically."))

    reg_row = None
    # 3. GST certificate vs registry
    if g:
        gs = g.get("gstin")
        if not gs:
            alt = find_by_name(g.get("trade_name") or "", 92)
            if len(alt) == 1:
                gs = alt[0]["gstin"]
                checks.append(_chk("gst_read", "GSTIN on certificate", "warn",
                                   "GSTIN could not be read clearly; matched by business name instead.",
                                   "Please confirm the GSTIN."))
        if gs:
            if claimed_gstin and claimed_gstin.upper() != gs:
                checks.append(_chk("gst_claim", "GSTIN matches what you entered", "fail",
                                   "The certificate GSTIN differs from the GSTIN entered earlier.",
                                   "Correct the GSTIN or upload the right certificate."))
            valid = gstin_is_valid(gs)
            checks.append(_chk("gst_format", "GSTIN format and checksum", "pass" if valid else "fail",
                               "Valid structure and checksum" if valid else "GSTIN fails the checksum"))
            reg_row = lookup_gstin(gs)
            if not reg_row:
                checks.append(_chk("gst_registry", "GSTIN found in registry", "fail",
                                   "This GSTIN is not in the registry.", "Check the number or contact support."))
            else:
                st = reg_row["status"]
                if st == "Active":
                    checks.append(_chk("gst_registry", "GST registration status", "pass", "Registry shows Active"))
                else:
                    # not a rejection: the customer can still buy products that do not need GST
                    checks.append(_chk("gst_registry", "GST registration status", "limit",
                                       f"Registry shows this GSTIN as {st}. Products that need GST are not available.",
                                       "Continue with the other products, or reinstate the GST registration and verify again."))
                ns = _name_score(g.get("legal_name", ""), reg_row["legal_name"])
                if ns >= 90:
                    checks.append(_chk("gst_name", "Name on certificate matches registry", "pass",
                                       "Legal name matches the GST registry"))
                else:
                    checks.append(_chk("gst_name", "Name on certificate matches registry", "fail",
                                       f"Certificate says '{g.get('legal_name')}' but the registry has '{reg_row['legal_name']}'.",
                                       "Upload the latest certificate or correct the business name."))
                if fuzz.ratio(_addr_norm(g.get("address", "")), _addr_norm(reg_row["principal_place_of_business"])) < 85:
                    checks.append(_chk("gst_addr_reg", "Address matches registry", "warn",
                                       "Address on the certificate differs from the registry.", "Please confirm."))
            sc = gs[:2]
            addr_state = _state_of(g.get("address", "")) or _state_of(a.get("address", ""))
            if addr_state and STATE_CODES.get(sc) and STATE_CODES[sc] != addr_state:
                checks.append(_chk("state", "GSTIN state matches address", "fail",
                                   f"GSTIN is registered in {STATE_CODES[sc]} but the address is in {addr_state}."))
            elif addr_state:
                checks.append(_chk("state", "GSTIN state matches address", "pass", f"Both point to {addr_state}"))

    # 4. Udyam
    if u:
        un = u.get("udyam_number")
        if not un:
            checks.append(_chk("udyam_number", "Udyam registration number", "fail",
                               "The Udyam number is missing on the certificate.", "Upload the full certificate."))
        else:
            row = lookup_udyam(un)
            if not row:
                checks.append(_chk("udyam_registry", "Udyam found in registry", "fail",
                                   "This Udyam number is not in the registry."))
            else:
                ok = _name_score(u.get("enterprise_name", ""), row["enterprise_name"]) >= 90
                checks.append(_chk("udyam_registry", "Udyam found in registry", "pass" if ok else "fail",
                                   "Registered and name matches" if ok else "Enterprise name differs from the registry"))
        if g and u.get("enterprise_name") and _name_score(u["enterprise_name"], g.get("trade_name", "")) < 85:
            checks.append(_chk("udyam_vs_gst", "Udyam name matches GST trade name", "warn",
                               "Business names differ between Udyam and GST certificates.", "Please confirm."))

    # 5. signatory
    if i:
        biz = (g.get("trade_name") if g else None) or (u.get("enterprise_name") if u else None)
        if biz and _name_score(i.get("business", ""), biz) < 85:
            checks.append(_chk("id_business", "Signatory ID is for this business", "fail",
                               "The ID card names a different business.", "Upload the right signatory ID."))
        vt = _first_date(i.get("valid_till", ""))
        if vt and vt < TODAY:
            checks.append(_chk("id_valid", "Signatory ID validity", "fail", f"ID expired on {vt}.",
                               "Upload a valid ID."))
        elif vt:
            checks.append(_chk("id_valid", "Signatory ID validity", "pass", f"Valid until {vt}"))
        des = (i.get("designation") or "").lower()
        const = (g.get("constitution") or "") if g else ""
        if des and des not in AUTHORISED:
            checks.append(_chk("id_authority", "Signatory is authorised", "warn",
                               f"Designation '{i.get('designation')}' cannot sign for the business on its own.",
                               "Upload an authorisation letter signed by the owner or a partner."))
        elif des:
            checks.append(_chk("id_authority", "Signatory is authorised", "pass", f"Designation: {i.get('designation')}"))
        if g and const.lower() == "proprietorship" and g.get("legal_name"):
            owner, _ = _prop_parts(g["legal_name"])
            if owner and i.get("name") and _name_score(owner, i["name"]) < 85:
                checks.append(_chk("id_owner", "Signatory matches proprietor", "fail",
                                   "For a proprietorship the signatory must be the proprietor named on the GST certificate.",
                                   "Upload the proprietor's ID or an authorisation letter."))

    # 6. address proof
    if a:
        bd = _first_date(a.get("bill_date", ""))
        if not bd:
            checks.append(_chk("bill_date", "Address proof date", "fail", "Could not read the bill date.",
                               "Upload a clearer bill."))
        else:
            age = (TODAY - bd).days
            if age < 0:
                checks.append(_chk("bill_date", "Address proof date", "fail", f"Bill is dated in the future ({bd})."))
            elif age > ADDRESS_PROOF_MAX_AGE_DAYS:
                checks.append(_chk("bill_date", "Address proof is recent", "fail",
                                   f"Bill dated {bd} is {age} days old; the limit is {ADDRESS_PROOF_MAX_AGE_DAYS} days.",
                                   f"Upload a bill dated on or after {TODAY.fromordinal(TODAY.toordinal() - ADDRESS_PROOF_MAX_AGE_DAYS)}."))
            else:
                checks.append(_chk("bill_date", "Address proof is recent", "pass", f"Bill dated {bd} ({age} days old)"))
        biz = (g.get("trade_name") if g else None) or (u.get("enterprise_name") if u else None)
        if biz and a.get("billed_to") and _name_score(a["billed_to"], biz) < 85:
            checks.append(_chk("bill_name", "Bill is in the business name", "warn",
                               f"Bill is addressed to '{a['billed_to']}', not the business.",
                               "Upload a bill in the business name or the owner's name with a rent agreement."))
        ref_addr = (g.get("address") if g else "") or (reg_row["principal_place_of_business"] if reg_row else "")
        if ref_addr and a.get("address"):
            same_pin = _pin(a["address"]) == _pin(ref_addr)
            sim = fuzz.ratio(_addr_norm(a["address"]), _addr_norm(ref_addr))
            if sim >= 85 and same_pin:
                checks.append(_chk("addr_match", "Bill address matches registered address", "pass", "Addresses match"))
            else:
                checks.append(_chk("addr_match", "Bill address matches registered address", "fail",
                                   f"Addresses differ (similarity {sim:.0f}%{', PIN code differs' if not same_pin else ''}).",
                                   "Upload a bill for the registered address or update the registration."))

    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    limits = [c for c in checks if c["status"] == "limit"]
    decision = "action_required" if fails else ("review" if warns else "verified")
    return {
        "decision": decision,
        "checks": checks,
        "restrictions": ["gst"] if limits else [],
        "summary": {"pass": sum(c["status"] == "pass" for c in checks), "warn": len(warns), "fail": len(fails),
                    "limit": len(limits)},
        "gstin_status": (reg_row or {}).get("status"),
        "gst_valid_for_sale": bool(reg_row and reg_row["status"] == "Active"),
    }
