"""Advisor flow tests run with Gemini disabled, proving the journey works on the deterministic path."""
import pytest

from app import advisor, llm
from app.db import ChatSession


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm, "available", lambda: False)


def run(lang, *msgs):
    s = ChatSession(id="t", language=lang, step="business_type", profile={}, extra={})
    out = None
    for m in msgs:
        out = advisor.handle(s, m)
    return s, out


def test_clinic_flow_reaches_recommendation_with_price():
    s, out = run("en", "I run a dental clinic", "5", "Nagpur", "Home broadband", "No GSTIN")
    assert out["done"] and out["recommendation"]
    q = out["recommendation"]["quote"]
    assert q["monthly_total"] > 0 and "₹" in out["reply"]
    assert s.profile["segment"] == "prof" and s.profile["city_tier"] == 2


def test_hindi_journey_uses_hindi_and_devanagari_digits():
    s, out = run("hi", "मेरी किराना दुकान है", "२", "जयपुर", "Mobile hotspot", "नहीं")
    assert out["done"] and "प्रति माह" in out["reply"]
    assert s.profile["employees"] == 2


def test_valid_gstin_is_verified_and_unlocks_gst_products():
    g = next(g for g, r in advisor.__dict__["lookup_gstin"].__globals__["gstin_registry"]().items()
             if r["status"] == "Active")
    s, out = run("en", "salon", "3", "Pune", "Home broadband", g)
    assert s.profile["has_valid_gstin"] is True
    assert "Verified" in out["reply"] and g not in out["reply"]  # identifier is masked


def test_cancelled_gstin_blocks_gst_products():
    g = next(g for g, r in advisor.__dict__["lookup_gstin"].__globals__["gstin_registry"]().items()
             if r["status"] == "Cancelled")
    s, out = run("en", "clinic", "6", "Delhi", "Business broadband", g)
    assert s.profile["has_valid_gstin"] is False
    ids = {i["product_id"] for i in out["recommendation"]["items"]}
    assert not ({"P12", "P15", "P21"} & ids)


def test_bad_gstin_checksum_is_rejected():
    s, out = run("en", "clinic", "6", "Delhi", "Business broadband", "27AAAAA0000A1Z5")
    assert not out["done"] and s.step == "gstin"


def test_judge_style_request_for_1g_in_tier2_is_explained_and_alternative_offered():
    s, out = run("en", "CA office", "3", "Nagpur", "Home broadband", "no", "I want a 1 Gbps leased fibre")
    assert "Sorry" in out["reply"] or "available" in out["reply"]
    s, out = run("en", "CA office", "3", "Nagpur", "Home broadband", "no", "can I get Biz Fibre 1G")
    assert "Sorry" in out["reply"] and "Tier" in out["reply"] or "employees" in out["reply"]


def test_whatsapp_api_without_gstin_is_refused_with_reason():
    s, out = run("en", "kirana store", "1", "Surat", "Mobile hotspot", "no", "add WhatsApp business API")
    assert "GSTIN" in out["reply"]


def test_cheaper_switches_to_24_months():
    s, out = run("en", "clinic", "5", "Mumbai", "Home broadband", "no")
    before = out["recommendation"]["quote"]["monthly_total"]
    s2 = s
    out2 = advisor.handle(s2, "this is too expensive")
    assert out2["recommendation"]["term"] == 24
    assert out2["recommendation"]["quote"]["monthly_total"] <= before


def test_unparseable_answer_reprompts_instead_of_advancing():
    s, out = run("en", "hmm not sure")
    assert s.step == "business_type" and not out["done"]
