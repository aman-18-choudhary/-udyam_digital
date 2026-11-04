"""End-to-end KYC checks on the 12 specimen applicants (slow: runs real OCR)."""
import glob
import os

import pytest

from app.config import DATA_DIR
from app.kyc import extract, validate

HINT = {"gst_certificate": "gst", "udyam_certificate": "udyam", "signatory_id": "id", "address_proof": "address"}


def run(k):
    docs = {}
    for f in sorted(glob.glob(str(DATA_DIR / "kyc_documents" / f"{k}_*.png"))):
        r = extract(f, forced_type=HINT[os.path.basename(f)[4:-4]])
        docs[r["doc_type"]] = r
    return validate(docs)


def failed(v):
    return {c["id"] for c in v["checks"] if c["status"] == "fail"}


@pytest.fixture(scope="module")
def results():
    return {f"K{n:02d}": run(f"K{n:02d}") for n in range(1, 13)}


@pytest.mark.parametrize("k", ["K03", "K05", "K06", "K10", "K12"])
def test_clean_applicants_verify(results, k):
    assert results[k]["decision"] == "verified", results[k]["checks"]


def test_k01_cancelled_gst_limits_products_and_missing_udyam_number_fails(results):
    k = results["K01"]
    assert "udyam_number" in failed(k)
    gst = next(c for c in k["checks"] if c["id"] == "gst_registry")
    assert gst["status"] == "limit" and k["restrictions"] == ["gst"] and not k["gst_valid_for_sale"]


def test_cancelled_gst_alone_is_a_limit_not_a_rejection():
    from app.kyc import validate as v
    res = results_k01_without_udyam_problem()
    assert res["decision"] in ("verified", "review") and res["restrictions"] == ["gst"]


def test_k02_tilted_photo_is_straightened_and_read(results):
    assert any(c["id"] == "deskew_gst" for c in results["K02"]["checks"])
    assert not failed(results["K02"])


def test_k04_blurred_certificate_is_rejected(results):
    assert "quality_gst" in failed(results["K04"])


def test_k07_legal_name_mismatch_is_caught(results):
    assert "gst_name" in failed(results["K07"])


def test_k11_stale_address_proof_is_rejected(results):
    assert "bill_date" in failed(results["K11"])


@pytest.mark.parametrize("k", ["K01", "K02", "K07", "K08", "K09"])
def test_non_owner_signatory_needs_review(results, k):
    assert any(c["id"] == "id_authority" and c["status"] == "warn" for c in results[k]["checks"])


def results_k01_without_udyam_problem():
    """K01 documents minus the Udyam certificate (the only other failure), so the cancelled GST stands alone."""
    docs = {}
    for f in sorted(glob.glob(str(DATA_DIR / "kyc_documents" / "K01_*.png"))):
        t = HINT[os.path.basename(f)[4:-4]]
        if t != "udyam":
            r = extract(f, forced_type=t)
            docs[r["doc_type"]] = r
    return validate(docs)
