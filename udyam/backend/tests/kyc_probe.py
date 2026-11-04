"""Dev helper: run the KYC pipeline over all 12 specimen applicants and print decisions."""
import glob
import os
import sys

from app.config import DATA_DIR
from app.kyc import extract, validate

base = DATA_DIR / "kyc_documents"
only = sys.argv[1:]
for k in [f"K{n:02d}" for n in range(1, 13)]:
    if only and k not in only:
        continue
    docs = {}
    for f in sorted(glob.glob(str(base / f"{k}_*.png"))):
        hint = {"gst_certificate": "gst", "udyam_certificate": "udyam", "signatory_id": "id",
                "address_proof": "address"}[os.path.basename(f)[4:-4]]
        r = extract(f, forced_type=hint)
        docs[r["doc_type"]] = r
    v = validate(docs)
    print(f"\n== {k}  -> {v['decision'].upper()}  {v['summary']}  gst={v['gstin_status']}")
    for c in v["checks"]:
        if c["status"] != "pass":
            print(f"   [{c['status']:4}] {c['label']}: {c['detail']}")
    g = docs.get("gst", {}).get("fields", {})
    if g:
        print("   gstin:", g.get("gstin"), g.get("gstin_method"), "| addr:", g.get("address"))
