# Data privacy and security note: Project Udyam Digital

**Principles.** Collect only what each step needs, tell the owner why before asking, protect it, and delete it on a
schedule. Aligned with the DPDP Act, 2023 (notice and consent, purpose limitation, data minimisation, storage
limitation, rights of the data principal, security safeguards).

| DPDP principle | What the system does |
|---|---|
| **Notice and consent** | A plain-language notice (what, why, not used for, protection, retention, rights) is shown before any document is requested. Consent is recorded per purpose (`kyc_verification`) with the notice version and timestamp. Without consent the API refuses to open a KYC case or accept a file (HTTP 403). |
| **Purpose limitation** | Documents are used only to verify the business and provision services. They are not used for marketing, profiling or the AI advisor. |
| **Data minimisation** | The owner enters a GSTIN first; registry lookup pre-fills details, so only documents the registry cannot confirm are requested. The advisor collects business type, headcount, sites, city tier and current internet, and no personal identifiers. |
| **No identifiers to the AI model** | Prompts to Gemini contain only the business profile and the already-priced bundle. GSTIN, Udyam numbers, names on documents and document images never leave the server. The free Gemini tier may use prompts to improve Google products, which is why identifiers are excluded by design. |
| **Masking** | GSTIN, Udyam and ID numbers are masked (last 4 characters) in every API response, UI element and log line. Raw values exist only inside the KYC service, in memory and in encrypted storage. |
| **Security safeguards** | Sign-in with Clerk; every API call verifies the signed token and customers can only read their own sessions, cases and orders (others get 404). Staff roles come from the signed token; documents can be opened only by the ops role and each view is audited. Data lives in Supabase Postgres with row level security on and no public API grants, and files in a private Supabase Storage bucket. Fernet (AES-128-CBC with HMAC) encryption for stored document files and extracted fields; key from environment or a 0600 key file, separate from the database. Upload size cap (8 MB), image validation, server-generated file names (no path traversal). Rate limits on advisor, lookup and upload endpoints. Prices recomputed server side. Append-only audit log of privacy-relevant actions with masked identifiers. |
| **Storage limitation** | Cases that are rejected or abandoned get a deletion date 30 days out (`KYC_RETENTION_DAYS_REJECTED`); `/api/admin/purge` (a scheduled job in production) deletes files and fields. Verified customers' records are kept for the period regulators require, then deleted. |
| **Rights: withdrawal and erasure** | One click on the verification screen withdraws consent and deletes all of that session's documents immediately; the action is audited. |
| **Payments** | Card, UPI and bank details are entered only in Razorpay Checkout and never reach our servers. We store the order amount, Razorpay order and payment ids, and the result. Payment confirmation is verified on the server (signature, amount, webhook). |
| **Human oversight** | Documents with warnings (for example a signatory who is not an owner) go to a manual review queue rather than being auto-approved or silently rejected. Every rejection explains what to fix. |

**Retention summary.** Chat profile: session only. Rejected or abandoned documents: 30 days. Verified customers: as
required by regulation, then deleted. Audit log: masked identifiers, kept for accountability.

**Residual risks and next steps.** Rotate the encryption key via a KMS, move storage to an encrypted object store,
add authenticated customer sessions and role-based access for the sales console (open in this demo), and run a DPIA
before launch.
