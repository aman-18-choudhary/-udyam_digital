# 3-minute demo script

Record at phone width (browser dev tools, 390 px) so "on a phone" is visible. Get a GSTIN to type from the
registry first: `cd backend && .venv/bin/python -c "from app.data import gstin_registry as r; print([k for k,v in r().items() if v['status']=='Active'][:1])"`.

| Time | Show | Say |
|---|---|---|
| 0:00 | Slide 2 or the funnel tab of the sales console | "7% of leads activate; 827 are lost to the sales visit, 385 to quotes, 273 to paperwork. We remove all three." |
| 0:15 | Advisor: Clinic, 5, Nagpur, Business broadband, paste the GSTIN | "Five questions. The GSTIN is verified live and masked. Price and eligibility come from rules, not the AI." |
| 0:50 | Type "I want Biz Fibre 1G" | "In a Tier-2 city it is refused with the exact reason and the nearest alternative. No dead-end quote." |
| 1:05 | Switch to Hindi (new session) for two answers | "Same journey in Hindi; ten languages with Gemini." |
| 1:15 | Quote: toggle CCTV, switch 12/24 months, remove the connectivity item | "One transparent price; dependencies are enforced, and the server recomputes the price at checkout." |
| 1:40 | KYC: consent screen, sample K03, Verify | "Consent first. OCR, registry lookups and cross-document checks in seconds." |
| 2:00 | Sample K11 (stale bill) then K04 (blurred) or K07 (name mismatch) | "It tells the owner exactly what to fix." |
| 2:15 | Withdraw consent | "One click deletes the documents." |
| 2:25 | Pay with "simulate decline", retry, tracker | "A failed payment is handled; the tracker updates live, no support calls." |
| 2:50 | Sales console: Leads to call | "The field force gets ranked leads with a next action. They accelerate, not compete." |
