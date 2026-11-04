"""Lead propensity for the sales / partner console (stretch goal).

A transparent smoothed naive-Bayes model on profile features only, then adjusted for how far the
lead progressed. No sklearn: the maths is ten lines and every score can be explained to a sales rep.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from functools import lru_cache

from .data import leads

FEATURES = ["segment", "lead_source", "city_tier", "preferred_language", "has_gstin", "has_udyam",
            "current_internet", "annual_turnover_band", "sites_bin", "emp_bin"]
STAGE_ORDER = ["Lead", "Contacted", "Needs assessed", "Quote accepted", "KYC complete"]
NEXT_ACTION = {
    "Price too high": "Offer the 24-month plan or the lighter Udyam Start bundle",
    "Competitor offered cheaper plan": "Send a price-match review and bundle savings summary",
    "Quote too complex to understand": "Resend the simplified one-price quote on WhatsApp",
    "Quote took too long to arrive": "Apologise and confirm the instant digital quote",
    "Decided to wait": "Schedule a reminder call in two weeks with an offer",
    "Missing GST or Udyam document": "Send the document checklist and GSTIN/Udyam lookup link",
    "Found paperwork too long": "Offer assisted KYC: pre-filled from the registry, upload only gaps",
    "Authorised signatory not available": "Send an authorisation-letter template and e-sign link",
    "Document details did not match": "Show the exact mismatch and how to fix it",
    "Installation delayed beyond 21 days": "Assign a partner to expedite installation",
    "Customer cancelled before install": "Call to understand the concern; offer a flexible term",
    "Site not feasible for fibre": "Offer 5G AirFiber, installable in about 2 days",
    "First payment failed": "Resend the payment link with UPI and card options",
}
DEFAULT_ACTION = "Follow up with the digital advisor link"


def _bin(v: str, edges: list[int]) -> str:
    try:
        n = int(v)
    except ValueError:
        return "?"
    for e in edges:
        if n <= e:
            return f"<={e}"
    return f">{edges[-1]}"


def _feats(r: dict) -> dict:
    d = {k: r.get(k, "") for k in FEATURES if k not in ("sites_bin", "emp_bin")}
    d["sites_bin"] = _bin(r["num_sites"], [1, 3, 6])
    d["emp_bin"] = _bin(r["employee_count"], [1, 3, 10, 25])
    return d


class Model:
    def __init__(self, rows: list[dict]):
        self.n = len(rows)
        self.pos = sum(r["outcome"] == "Activated" for r in rows)
        self.base = (self.pos + 1) / (self.n + 2)
        self.cnt: dict = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for r in rows:
            y = r["outcome"] == "Activated"
            for k, v in _feats(r).items():
                self.cnt[k][v][1] += 1
                if y:
                    self.cnt[k][v][0] += 1

    def log_odds(self, r: dict) -> float:
        lo = math.log(self.base / (1 - self.base))
        for k, v in _feats(r).items():
            a, n = self.cnt[k][v]
            p = (a + 1) / (n + 2)
            lo += math.log((p / (1 - p)) / (self.base / (1 - self.base))) * 0.6  # damped: features overlap
        return lo

    def prob(self, r: dict) -> float:
        return 1 / (1 + math.exp(-self.log_odds(r)))


def _auc(scores: list[tuple[float, int]]) -> float:
    pos = [s for s, y in scores if y]
    neg = [s for s, y in scores if not y]
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


@lru_cache(maxsize=1)
def model() -> tuple[Model, float]:
    rows = list(leads())
    random.Random(7).shuffle(rows)
    cut = int(len(rows) * 0.7)
    train, test = rows[:cut], rows[cut:]
    m = Model(train)
    auc = _auc([(m.prob(r), int(r["outcome"] == "Activated")) for r in test])
    return Model(rows), round(auc, 3)


@lru_cache(maxsize=1)
def stage_odds() -> dict[str, float]:
    """P(activated | reached this stage) from the data, used to lift leads that got further."""
    out = {}
    rows = leads()
    for i, st in enumerate(STAGE_ORDER):
        reached = [r for r in rows if r["stage_reached"] in STAGE_ORDER[i:] or r["outcome"] == "Activated"]
        a = sum(r["outcome"] == "Activated" for r in reached)
        out[st] = (a + 1) / (len(reached) + 2)
    return out


def score_open_leads(limit: int = 25, min_stage: str = "Needs assessed", segment: str | None = None) -> list[dict]:
    m, _ = model()
    so = stage_odds()
    base_odds = m.base / (1 - m.base)
    rows = []
    for r in leads():
        if r["outcome"] != "Dropped":
            continue
        if STAGE_ORDER.index(r["stage_reached"]) < STAGE_ORDER.index(min_stage):
            continue
        if segment and r["segment"] != segment:
            continue
        p0 = m.prob(r)
        ps = so[r["stage_reached"]]
        odds = (p0 / (1 - p0)) * ((ps / (1 - ps)) / base_odds)
        p = odds / (1 + odds)
        rows.append({
            "lead_id": r["lead_id"], "business": r["business_name"], "segment": r["segment"], "city": r["city"],
            "source": r["lead_source"], "stage_reached": r["stage_reached"], "drop_reason": r["drop_reason"],
            "has_gstin": r["has_gstin"] == "Y", "score": round(p, 3),
            "next_action": NEXT_ACTION.get(r["drop_reason"], DEFAULT_ACTION),
        })
    rows.sort(key=lambda x: -x["score"])
    return rows[:limit]


def funnel() -> dict:
    rows = leads()
    stages = ["Lead", "Contacted", "Needs assessed", "Quote accepted", "KYC complete", "Activated"]
    counts = []
    for i, st in enumerate(stages):
        if st == "Activated":
            counts.append(sum(r["outcome"] == "Activated" for r in rows))
        else:
            counts.append(sum(r["stage_reached"] in STAGE_ORDER[i:] or r["outcome"] == "Activated" for r in rows))
    return {"stages": stages, "counts": counts}
