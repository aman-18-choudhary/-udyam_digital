"""Deterministic business rules: eligibility, bundle recommendation, pricing and validation.

The LLM never decides price or eligibility. It only explains what this module computed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

from .data import Product, catalogue

SEGMENTS = {
    "micro": "Micro retail & services",
    "prof": "Professional offices",
    "multi": "Small multi-site business",
    "mfg": "Small manufacturer",
}
GST_RATE = 0.18


@dataclass
class Profile:
    segment: str = "micro"
    employees: int = 1
    sites: int = 1
    city_tier: int = 1
    has_valid_gstin: bool = False
    current_internet: str = ""
    language: str = "en"
    wants: set[str] = field(default_factory=set)


@dataclass
class Item:
    product_id: str
    qty: int
    role: str  # core | recommended | optional
    included: bool
    why: str = ""


# ---------------------------------------------------------------- eligibility
def eligibility(p: Product, prof: Profile, bundle_ids: set[str] | None = None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if prof.city_tier not in p.tiers:
        reasons.append(f"{p.name} is sold in Tier {'/'.join(map(str, p.tiers))} cities only")
    if prof.employees < p.min_employees:
        reasons.append(f"{p.name} needs at least {p.min_employees} employees")
    if prof.sites < p.min_sites:
        reasons.append(f"{p.name} needs at least {p.min_sites} sites")
    if p.requires_gstin and not prof.has_valid_gstin:
        reasons.append(f"{p.name} needs a valid, active GSTIN")
    if bundle_ids is not None and p.requires_one_of and not (set(p.requires_one_of) & bundle_ids):
        names = " / ".join(catalogue()[i].name for i in p.requires_one_of if i in catalogue())
        reasons.append(f"{p.name} needs an internet link in the same bundle ({names})")
    return (not reasons), reasons


# ---------------------------------------------------------------- quantities
def default_qty(p: Product, prof: Profile) -> int:
    u = p.unit
    if u == "per site":
        return max(1, prof.sites)
    if u == "per user":
        return max(1, min(prof.employees, 50))
    if u == "per line":
        return max(1, min(math.ceil(prof.employees / 2), 5))
    if u == "per channel":
        return max(p.min_employees, min(prof.employees // 4, 10))
    if u == "per camera":
        base = {"micro": 1, "prof": 2, "multi": 2, "mfg": 4}[prof.segment]
        return min(base * max(1, prof.sites), 8)
    if u == "per counter":
        return max(1, prof.sites)
    if u == "per device":
        if p.id == "P20":
            return max(1, min(prof.employees, 20))
        return 5  # IoT sensor kit
    if u == "per vehicle":
        return 2
    return 1  # per account / pack / number / IP


WHY = {
    "P01": "Steady fibre internet so billing, UPI and cloud tools never stall.",
    "P02": "Faster fibre for a team that works online all day, with an optional fixed IP.",
    "P03": "1 Gbps fibre with priority support for heavy daily use.",
    "P04": "Plug-and-play wireless internet, live in about 2 days, no cable work needed.",
    "P05": "A dedicated line with a 99.5% uptime promise for machines and ERP access.",
    "P06": "A dedicated 100 Mbps line with 99.9% uptime for high-volume sites.",
    "P07": "Business mobile lines with calls and data for you and your team.",
    "P08": "Higher data, roaming and priority care for people who travel for work.",
    "P09": "A backup link that switches on automatically when the main internet drops.",
    "P10": "One dashboard to manage the internet at every site and prioritise key apps.",
    "P11": "A fixed public IP so cameras or remote access always find you.",
    "P12": "Business phone numbers over the internet with call recording.",
    "P13": "A 1800 number so customers can call you free of charge.",
    "P14": "Send appointment, order and promo SMS to customers (DLT help included).",
    "P15": "A verified WhatsApp business channel with your catalogue for customers.",
    "P16": "Business email on your own name plus documents and video meetings.",
    "P17": "Automatic backup of PCs and phones so one crash never loses your records.",
    "P18": "A domain and a simple website so customers can find you online.",
    "P19": "GST-ready billing, stock and UPI/card acceptance on a tablet.",
    "P20": "Protects your computers and phones against viruses and ransomware.",
    "P21": "A managed firewall watched by Accel's security team.",
    "P22": "Managed Wi-Fi with a separate guest network for your customers.",
    "P23": "HD cameras with 30 days of cloud recording you can watch from your phone.",
    "P24": "Sensors that track machine uptime and power use.",
    "P25": "Live GPS tracking for your delivery vehicles.",
}

# (product id, role) per segment, in display order. Connectivity is chosen separately.
_ADDONS: dict[str, list[tuple[str, str]]] = {
    "micro": [("P07", "core"), ("P19", "recommended"), ("P23", "optional"), ("P15", "optional"),
              ("P18", "optional"), ("P22", "optional")],
    "prof": [("P09", "recommended"), ("P16", "core"), ("P17", "recommended"), ("P20", "recommended"),
             ("P07", "recommended"), ("P23", "optional"), ("P22", "optional"), ("P11", "optional"),
             ("P12", "optional"), ("P15", "optional"), ("P21", "optional")],
    "multi": [("P22", "recommended"), ("P23", "recommended"), ("P09", "recommended"), ("P10", "recommended"),
              ("P16", "recommended"), ("P20", "recommended"), ("P07", "recommended"), ("P19", "optional"),
              ("P13", "optional"), ("P15", "optional")],
    "mfg": [("P21", "recommended"), ("P24", "recommended"), ("P07", "core"), ("P09", "recommended"),
            ("P20", "optional"), ("P23", "optional"), ("P25", "optional"), ("P08", "optional")],
}

# product id -> the "want" keyword that switches an optional item on
_WANT_TO_PRODUCT = {
    "cctv": "P23", "camera": "P23", "pos": "P19", "billing": "P19", "whatsapp": "P15", "website": "P18",
    "wifi": "P22", "phone": "P12", "tollfree": "P13", "iot": "P24", "fleet": "P25", "backup": "P17",
    "email": "P16", "security": "P21", "sms": "P14",
}


def _pick_connectivity(prof: Profile) -> tuple[Product, list[str]]:
    """Choose the primary internet link and report links that were considered but not allowed."""
    cat = catalogue()
    notes: list[str] = []
    avg_staff_per_site = prof.employees / max(1, prof.sites)
    if prof.segment == "mfg":
        order = ["P06", "P05", "P03", "P02", "P01"]
    elif prof.segment == "multi":
        order = ["P03", "P02", "P01"] if avg_staff_per_site >= 15 else ["P02", "P01"]
    elif prof.segment == "prof":
        order = ["P02", "P01"] if prof.employees >= 5 else ["P01", "P04"]
    else:  # micro
        order = ["P04", "P01"]
    for pid in order:
        ok, reasons = eligibility(cat[pid], prof)
        if ok:
            return cat[pid], notes
        notes.extend(reasons)
    return cat["P04"], notes  # wireless has no gates, so there is always an answer


def recommend(prof: Profile) -> dict:
    """Return the recommended bundle, the products left out and why."""
    cat = catalogue()
    items: list[Item] = []
    excluded: list[dict] = []

    link, notes = _pick_connectivity(prof)
    items.append(Item(link.id, default_qty(link, prof), "core", True, WHY[link.id]))
    for n in notes[:2]:
        excluded.append({"product_id": None, "reason": n})
    link_ids = {link.id}

    for pid, role in _ADDONS[prof.segment]:
        p = cat[pid]
        ok, reasons = eligibility(p, prof, link_ids)
        if not ok:
            excluded.append({"product_id": pid, "name": p.name, "reason": reasons[0]})
            continue
        wanted = any(_WANT_TO_PRODUCT.get(w) == pid for w in prof.wants)
        included = role in ("core", "recommended") or wanted
        items.append(Item(pid, default_qty(p, prof), role if not wanted else "recommended", included, WHY[pid]))

    return {"items": [asdict(i) for i in items], "excluded": excluded}


# ---------------------------------------------------------------- pricing
def _price_factor(contract: int, n_products: int) -> float:
    f = 0.0 if contract >= 24 else (0.5 if contract >= 12 else 1.0)
    if n_products >= 3:
        f = max(0.0, f - 0.25)
    return f


def quote(items: list[dict], prof: Profile, term: int = 12) -> dict:
    """Price a bundle. `items` = [{product_id, qty, included}]. Always returns one transparent total."""
    cat = catalogue()
    chosen = [i for i in items if i.get("included", True) and i["qty"] > 0]
    n = len(chosen)
    lines, monthly, setup, install = [], 0, 0, 0
    for i in chosen:
        p = cat[i["product_id"]]
        contract = max(p.min_contract, term) if p.min_contract >= 6 else p.min_contract
        f = _price_factor(contract, n)
        unit = round(p.price_min + (p.price_max - p.price_min) * f)
        line_m = unit * i["qty"]
        line_s = p.setup * i["qty"]
        monthly += line_m
        setup += line_s
        install = max(install, p.install_days)
        lines.append({
            "product_id": p.id, "name": p.name, "unit": p.unit, "qty": i["qty"], "unit_price": unit,
            "monthly": line_m, "setup": line_s, "contract_months": contract,
            "list_range": [p.price_min, p.price_max],
        })
    gst_m = round(monthly * GST_RATE)
    gst_s = round(setup * GST_RATE)
    return {
        "lines": lines,
        "term_months": term,
        "monthly_subtotal": monthly,
        "monthly_gst": gst_m,
        "monthly_total": monthly + gst_m,
        "setup_subtotal": setup,
        "setup_gst": gst_s,
        "setup_total": setup + gst_s,
        "first_payment": monthly + gst_m + setup + gst_s,
        "install_days": install,
        "bundle_discount_applied": n >= 3,
        "pricing_note": ("Prices sit inside the catalogue range: lowest for 24-month commitments, "
                         "midpoint for 12 months, highest for flexible terms; 3+ products earn an extra step down. "
                         "GST at 18% is added."),
    }


# ---------------------------------------------------------------- validation
def validate_bundle(items: list[dict], prof: Profile) -> list[dict]:
    """Server side rule check run on every checkout change. Returns a list of problems."""
    cat = catalogue()
    chosen = [i for i in items if i.get("included", True) and i["qty"] > 0]
    ids = {i["product_id"] for i in chosen}
    problems = []
    if not chosen:
        problems.append({"product_id": None, "code": "empty", "message": "Pick at least one product."})
    for i in chosen:
        p = cat.get(i["product_id"])
        if not p:
            problems.append({"product_id": i["product_id"], "code": "unknown", "message": "Unknown product."})
            continue
        ok, reasons = eligibility(p, prof, ids)
        if not ok:
            code = "dependency" if "same bundle" in reasons[0] else "eligibility"
            problems.append({"product_id": p.id, "code": code, "message": reasons[0]})
    return problems
