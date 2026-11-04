# Project Udyam Digital

A digital-first acquisition and onboarding journey for small businesses, built for the Airtel Sync 2026 case
(Accel Business, fictional operator). A small business owner can, on a phone and in their own language:

1. **Advise**: answer a few questions and get a bundle recommendation with a plain-language "why".
2. **Quote**: see one transparent monthly price, toggle add-ons, pick a 12 or 24 month commitment.
3. **Verify (Smart KYC)**: consent screen, registry lookups, document OCR and cross-document validation.
4. **Pay**: test-mode payment, including a simulated bank decline.
5. **Track**: a live order tracker (server-sent events) instead of calling support.

Plus a **sales / partner console** with the leads the digital journey did not close, ranked by a propensity
score with a suggested next action, and a list of customers who asked for a human.

## Two ways to run it

**Production-style (Supabase + Clerk).** Postgres and document storage in Supabase, sign-in with Clerk, roles for
staff. Follow [docs/SETUP_PRODUCTION.md](docs/SETUP_PRODUCTION.md); it covers creating the project, the bucket, the
Clerk session-token claim, the environment variables and the migration command (`alembic upgrade head`).

**Local development (no accounts needed).** SQLite and local disk, auth off (the UI shows an "Auth off (dev)" badge).

```bash
# 1. backend
cd udyam/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt     # also: brew install tesseract
cp .env.example .env          # add GEMINI_API_KEY (free, aistudio.google.com/apikey); leave the rest blank
.venv/bin/uvicorn app.main:app --port 8000

# 2. frontend (new terminal)
cd udyam/frontend && npm install && npm run dev                          # http://127.0.0.1:5173
```

Without a Gemini key the advisor still works in English and Hindi. With one it understands free-form answers and
supports ten Indian languages.

`DEMO_MODE=true` adds a sample-applicant picker (K01-K12), a "simulate a bank decline" option and an order timer
that advances installation automatically. It is off by default; without it, staff advance orders from the console.
The case's specimen documents are dated against **2026-07-15**; set `UDYAM_TODAY=2026-07-15` to evaluate with them
(leave it unset in production so real dates are used).

## Scenarios to try (set DEMO_MODE=true to load the sample applicants with one click, or upload the files from `YTL_TrackA_Udyam_Digital_Data/kyc_documents`)

| Scenario | What to do | What you should see |
|---|---|---|
| Happy path | Clinic, 5 people, Nagpur, any internet, a GSTIN from the registry | Bundle of about ₹5.9k/month incl. GST |
| Eligibility is enforced | Ask "I want Biz Fibre 1G" in a Tier-2 city | Refusal with the exact reason and the closest option |
| GST gating | Say "no GSTIN", then "add WhatsApp business API" | Refused: needs a valid, active GSTIN |
| Cancelled GST | Verify sample applicant **K01** | GST status fails, missing Udyam number flagged |
| Tilted photo | Sample **K02** | Straightened automatically and read |
| Blurred photo | Sample **K04** | Rejected as unreadable with a re-upload prompt |
| Name mismatch | Sample **K07** | Certificate legal name differs from the registry |
| Stale bill | Sample **K11** | Address proof is 257 days old, limit 90 |
| Non-owner signatory | Sample **K08 / K09** | Needs an authorisation letter (manual review) |
| Clean verification | Samples **K03, K05, K06, K10, K12** | Verified |
| Failed payment | Tick "Simulate a bank decline" | Handled, retry succeeds |
| Human handoff | Say "talk to a human" | Appears in the sales console under Handoffs |
| Consent withdrawal | "Withdraw consent & delete" on the verify screen | Documents are deleted from disk and the case is gone |

## Tests

```bash
cd udyam/backend && .venv/bin/python -m pytest      # 64 tests, about 55 s (includes real OCR)
TEST_DATABASE_URL=postgresql://... .venv/bin/python -m pytest tests/test_api.py tests/test_production.py   # on real Postgres
```

## Layout

```
udyam/
  backend/app/
    rules.py        eligibility, bundle recommendation, pricing, validation (no LLM)
    advisor.py      conversation state machine, parsers, product-request handling
    llm.py          Gemini adapter with circuit breaker; prompts never contain identifiers
    kyc.py          deskew, blur check, OCR, field parsing, cross-document validation
    registry.py     GSTIN checksum, OCR repair, mock GSTIN / Udyam lookup
    payments.py     Razorpay order, signature + amount verification, webhook
    orders.py       order pipeline and SSE tracker
    propensity.py   lead scoring for the sales console
    auth.py         Clerk JWT verification, roles (customer / sales / ops / admin)
    storage.py      Supabase Storage (private bucket) or local disk; ciphertext only
    crypto.py       encryption of KYC data and files at rest
    main.py         FastAPI routes, rate limits, consent and retention
  frontend/         React + Vite, mobile first
  backend/alembic/  database migrations (RLS on for Supabase)
  docs/             setup, architecture, privacy note, demo script
```
