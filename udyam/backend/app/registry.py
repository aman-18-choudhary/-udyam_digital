"""GSTIN / Udyam format checks and the mock registry lookup "APIs"."""
from __future__ import annotations

import re

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .data import gstin_registry, udyam_registry

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")

STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "32": "Kerala", "33": "Tamil Nadu", "36": "Telangana", "37": "Andhra Pradesh",
}
UDYAM_STATE = {
    "AP": "Andhra Pradesh", "DL": "Delhi", "GJ": "Gujarat", "KA": "Karnataka", "KL": "Kerala",
    "MH": "Maharashtra", "PB": "Punjab", "RJ": "Rajasthan", "TN": "Tamil Nadu", "TS": "Telangana",
    "UP": "Uttar Pradesh", "WB": "West Bengal", "HR": "Haryana", "MP": "Madhya Pradesh",
}


def gstin_checksum_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = _CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return _CHARS[(36 - total % 36) % 36]


def gstin_is_valid(g: str) -> bool:
    g = g.strip().upper()
    # README: the 4th PAN character is always "X" here, so we only check structure and checksum.
    return bool(GSTIN_RE.match(g)) and gstin_checksum_char(g[:14]) == g[14]


def mask(identifier: str, keep: int = 4) -> str:
    """Mask an identifier for logs and the UI: keep only the last `keep` characters."""
    if not identifier:
        return ""
    if len(identifier) <= keep:
        return "*" * len(identifier)
    return "*" * (len(identifier) - keep) + identifier[-keep:]


# Characters tesseract commonly confuses, used for repairing OCR output.
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7"}
_TO_ALPHA = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "7": "T"}


def _positional_fix(g: str) -> str:
    """Force digits/letters to the positions the GSTIN structure requires."""
    g = re.sub(r"[^A-Z0-9]", "", g.upper())
    out = []
    for i, ch in enumerate(g[:15]):
        if i in (0, 1, 7, 8, 9, 10):  # state code and PAN digits
            ch = _TO_DIGIT.get(ch, ch)
        elif i in (2, 3, 4, 5, 6, 11):  # PAN letters
            ch = _TO_ALPHA.get(ch, ch)
        out.append(ch)
    return "".join(out)


def repair_gstin(raw: str) -> tuple[str | None, str]:
    """Try to turn noisy OCR text into a registry GSTIN.

    Returns (gstin or None, method) where method explains how it was obtained.
    """
    cand = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if gstin_is_valid(cand) and cand in gstin_registry():
        return cand, "exact"
    fixed = _positional_fix(cand)
    if gstin_is_valid(fixed):
        return fixed, "ocr-char-fix"
    # Last resort: nearest registry entry with the same state prefix, within edit distance 3.
    best, best_d = None, 99
    for g in gstin_registry():
        d = Levenshtein.distance(fixed, g, score_cutoff=4)
        if d < best_d:
            best, best_d = g, d
    if best is not None and best_d <= 3:
        return best, f"registry-nearest(d={best_d})"
    return None, "unrecognised"


def lookup_gstin(gstin: str) -> dict | None:
    return gstin_registry().get((gstin or "").strip().upper())


def lookup_udyam(num: str) -> dict | None:
    return udyam_registry().get((num or "").strip().upper())


def normalise_udyam(raw: str) -> str | None:
    """Tolerant parse of OCR text such as 'UDYAM- AP- @0-9751562' (the slashed zero reads as '@')."""
    s = re.sub(r"[^A-Z0-9]", "", (raw or "").upper().replace("@", "0"))
    m = re.match(r"^UDYAM([A-Z]{2})([0-9O]{9,})$", s)
    if not m:
        return None
    digits = m.group(2).replace("O", "0")
    # The case data always uses district 00, so only the last 7 digits carry information.
    return f"UDYAM-{m.group(1)}-00-{digits[-7:]}"


def find_by_name(name: str, threshold: int = 90) -> list[dict]:
    """Find GST registry rows by trade or legal name (used when OCR of the number fails)."""
    out = []
    for r in gstin_registry().values():
        s = max(fuzz.token_sort_ratio(name.lower(), r["trade_name"].lower()),
                fuzz.token_sort_ratio(name.lower(), r["legal_name"].lower()))
        if s >= threshold:
            out.append({**r, "_score": s})
    return sorted(out, key=lambda r: -r["_score"])
