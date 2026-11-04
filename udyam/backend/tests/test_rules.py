from app.data import catalogue
from app.registry import gstin_is_valid, repair_gstin, gstin_checksum_char
from app.data import gstin_registry
from app.rules import Profile, recommend, quote, validate_bundle, eligibility


def test_every_registry_gstin_passes_checksum():
    assert all(gstin_is_valid(g) for g in gstin_registry())


def test_ocr_noise_is_repaired_to_registry_gstin():
    g, how = repair_gstin("27XUIXG0767D12P")
    assert g == "27XUIXG0767D1ZP" and g in gstin_registry()


def test_tier2_shop_cannot_get_1g_fibre():
    p = Profile(segment="prof", employees=3, sites=1, city_tier=2, has_valid_gstin=True)
    ok, reasons = eligibility(catalogue()["P03"], p)
    assert not ok and any("Tier" in r or "employees" in r for r in reasons)


def test_no_gstin_means_no_gstin_products():
    p = Profile(segment="micro", employees=2, city_tier=1, has_valid_gstin=False)
    rec = recommend(p)
    ids = {i["product_id"] for i in rec["items"]}
    assert "P15" not in ids  # WhatsApp API needs GSTIN
    assert any(e.get("product_id") == "P15" for e in rec["excluded"])


def test_dependency_enforced_on_checkout():
    p = Profile(segment="micro", employees=2, city_tier=1, has_valid_gstin=False)
    problems = validate_bundle([{"product_id": "P23", "qty": 1, "included": True}], p)
    assert any(x["code"] == "dependency" for x in problems)


def test_firewall_needs_connectivity_gstin_and_size():
    p = Profile(segment="prof", employees=12, city_tier=1, has_valid_gstin=True)
    ok_items = [{"product_id": "P02", "qty": 1}, {"product_id": "P21", "qty": 1}]
    assert validate_bundle(ok_items, p) == []
    small = Profile(segment="prof", employees=4, city_tier=1, has_valid_gstin=True)
    assert validate_bundle(ok_items, small)


def test_professional_bundle_price_in_expected_band():
    p = Profile(segment="prof", employees=5, sites=1, city_tier=1, has_valid_gstin=True, wants={"cctv"})
    rec = recommend(p)
    q = quote([i for i in rec["items"]], p, term=12)
    assert 3500 <= q["monthly_subtotal"] <= 7000
    assert q["monthly_total"] == q["monthly_subtotal"] + q["monthly_gst"]
    for line in q["lines"]:
        lo, hi = line["list_range"]
        assert lo <= line["unit_price"] <= hi


def test_longer_commitment_is_cheaper():
    p = Profile(segment="prof", employees=5, city_tier=1, has_valid_gstin=True)
    items = recommend(p)["items"]
    assert quote(items, p, 24)["monthly_subtotal"] <= quote(items, p, 12)["monthly_subtotal"]


def test_recommendation_is_always_valid():
    for seg in ("micro", "prof", "multi", "mfg"):
        for tier in (1, 2):
            for gst in (True, False):
                for emp, sites in ((1, 1), (6, 1), (15, 3), (40, 5)):
                    p = Profile(segment=seg, employees=emp, sites=sites, city_tier=tier, has_valid_gstin=gst)
                    items = [i for i in recommend(p)["items"] if i["included"]]
                    assert items, (seg, tier, gst, emp, sites)
                    assert validate_bundle(items, p) == [], (seg, tier, gst, emp, sites)
