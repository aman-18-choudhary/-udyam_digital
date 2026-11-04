# Production setup: Supabase + Clerk

Architecture in one line: **React app (Clerk sign-in) → FastAPI (verifies the Clerk token) → Supabase Postgres
(data) and a private Supabase Storage bucket (encrypted documents).** Gemini is used for the conversation only.

| Concern | Service | Why |
|---|---|---|
| Relational data (sessions, consents, KYC cases, orders, audit log) | **Supabase Postgres** | Managed Postgres, daily backups, point-in-time recovery on paid plans |
| KYC document files | **Supabase Storage** (private bucket) | Never public; the API reads/writes with a server-side key; files are also Fernet-encrypted before upload |
| Login | **Clerk** | Email / phone OTP, sessions, user management; the API verifies its JWT |
| Schema changes | **Alembic** | Versioned, reviewable migrations |
| AI conversation | **Gemini** | Receives business profile only, never identifiers |

## 1. Supabase

1. **Create a project** at supabase.com. Pick the region closest to your users (Mumbai `ap-south-1` for India).
   Save the database password somewhere safe.
2. **Database URL.** Click **Connect** in the dashboard, copy the **Session pooler** URI (port 5432). Replace
   `[YOUR-PASSWORD]`. This is `DATABASE_URL`. (If you deploy to a serverless platform with many short-lived
   connections, use the **Transaction pooler** URI on port 6543 instead; the app disables prepared statements for it
   automatically.)
3. **Create the tables:**
   ```bash
   cd udyam/backend
   DATABASE_URL='postgresql://postgres.xxxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres' \
     .venv/bin/alembic upgrade head
   ```
   Check **Table Editor**: the tables should show **RLS enabled**. This matters: Supabase exposes every table in the
   `public` schema through its public REST API, so the migration turns on row level security with no policies and
   revokes the `anon` and `authenticated` roles. Only the API server (which connects as the table owner) can read data.
4. **Create the bucket.** Storage → New bucket → name `kyc-documents`, **Public bucket OFF**, file size limit 10 MB.
5. **Storage keys.** Project Settings → API: copy the **Project URL** (`SUPABASE_URL`) and the **service_role** key
   (`SUPABASE_SERVICE_ROLE_KEY`). If your project shows the newer key format, open the *Legacy API keys* tab to get the
   `service_role` JWT, which this code sends as both `apikey` and `Authorization: Bearer`.
   **The service_role key bypasses all security. It lives only on the API server; never put it in the frontend or git.**
6. **Backups.** Free plan: take your own `pg_dump` regularly. Pro plan: enable daily backups, and PITR for production.

## 2. Clerk

1. Create an application at clerk.com. Enable the sign-in methods you want (phone OTP suits small-business owners;
   email works everywhere).
2. **Frontend key.** API Keys → copy the **Publishable key** into `frontend/.env` as `VITE_CLERK_PUBLISHABLE_KEY`.
3. **Backend issuer.** API Keys → *Show API URLs* → copy the **Frontend API URL** (like
   `https://something.clerk.accounts.dev`) into the backend as `CLERK_ISSUER`. The API downloads Clerk's public
   keys from `{CLERK_ISSUER}/.well-known/jwks.json` and verifies every token's signature, expiry and issuer.
4. **Roles in the token.** Sessions → *Customize session token* → set
   ```json
   { "metadata": "{{user.public_metadata}}" }
   ```
5. **Make staff.** Users → pick the user → *Public metadata* →
   `{ "role": "sales" }` (read the sales console), `{ "role": "ops" }` (review documents, approve, advance orders) or
   `{ "role": "admin" }`. Everyone else is a customer. Metadata can only be edited from the dashboard or the backend
   API, never by the user, and it is read from the signed token, so a customer cannot promote themselves.
6. **Authorized parties** (optional hardening): set `CLERK_AUTHORIZED_PARTIES` to your site origins, e.g.
   `http://localhost:5173,https://udyam.example.com`.

## 3. Razorpay (payments)

How a payment works: the server creates a Razorpay order for the exact amount, the browser opens Razorpay Checkout,
and the server confirms the payment itself: it checks the HMAC signature Razorpay returns, fetches the payment and
compares order id, currency, status and amount, and refuses to reuse one payment for two orders. A signed webhook
confirms payments even if the customer closes the tab right after paying. The browser can never mark an order paid.
When Razorpay keys are set, the test-mode `/pay` endpoint is disabled.

1. Create an account at razorpay.com and stay in **Test mode** (toggle in the dashboard) until everything works.
2. **API keys:** Account & Settings → API Keys → *Generate Test Key*. Put the Key Id in `RAZORPAY_KEY_ID` and the
   Key Secret in `RAZORPAY_KEY_SECRET` (backend `.env` only). The Key Id is public by design; the secret is not.
3. **Webhook:** Account & Settings → Webhooks → *Add new webhook*.
   * URL: `https://<your-api-domain>/api/webhooks/razorpay` (Razorpay must be able to reach it; for local testing
     use a tunnel such as `cloudflared tunnel --url http://localhost:8000` or ngrok).
   * Secret: choose a long random string and put the same value in `RAZORPAY_WEBHOOK_SECRET`.
   * Events: `payment.captured`, `payment.failed`, `order.paid`.
4. **Capture:** Settings → Payment Capture → *Automatic* (the order is created with `payment_capture: 1`).
5. **Test it:** pay with UPI id `success@razorpay` (and `failure@razorpay` for a failure), or the test card Razorpay
   publishes in its docs. Check `GET /api/health` shows `"payments":"razorpay"`.
6. **Go live:** finish Razorpay's business activation, generate **Live** keys (`rzp_live_…`), replace the three
   values, and create the webhook again in Live mode (webhook secrets are per mode).

Not built: refunds, settlement reconciliation and GST tax invoices. Use the Razorpay dashboard for refunds for now.

## 4. Environment variables

`udyam/backend/.env` (see `.env.example`):

| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres.xxx:pw@…pooler.supabase.com:5432/postgres` | Supabase Postgres |
| `SUPABASE_URL` | `https://xxxx.supabase.co` | |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJ…` | Server only |
| `SUPABASE_BUCKET` | `kyc-documents` | |
| `CLERK_ISSUER` | `https://xxx.clerk.accounts.dev` | Turns authentication on |
| `CLERK_AUTHORIZED_PARTIES` | `https://udyam.example.com` | Optional |
| `KYC_ENC_KEY` | output of `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` | **Back this up.** Losing it makes stored documents unreadable. Required in production (otherwise a key file is generated beside the app) |
| `GEMINI_API_KEY` | | Free tier works |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | `rzp_test_…` | Turns real online payment on; server only for the secret |
| `RAZORPAY_WEBHOOK_SECRET` | random string | Must match the webhook you create in Razorpay |
| `CORS_ORIGINS` | `https://udyam.example.com` | |
| `UDYAM_TODAY` | `2026-07-15` | **Only** when testing with the case's specimen documents. Leave unset in production so real dates are used |
| `DEMO_MODE` | `false` | `true` enables sample applicants and an auto-advancing order timer |

`udyam/frontend/.env`: `VITE_CLERK_PUBLISHABLE_KEY=pk_test_…`

## 5. Run it

```bash
# backend
cd udyam/backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --port 8000
# frontend
cd udyam/frontend && npm run dev
```
Check `GET /api/health`: it should say `"db":"up"`, `"storage":"supabase"`, `"auth":"clerk"`.

Container deployment (API + nginx web; the database and storage live in Supabase):
```bash
cd udyam && cp backend/.env.example backend/.env   # fill it in
docker compose up --build                          # web on :8080, proxies /api to the API
```
Use one origin for web and API (the bundled nginx does this) so server-sent events are not buffered by a proxy.

## 6. Operating it

* **Staff workflow.** Customers pay, then ops staff open **Staff console → Orders** and press *Advance* as
  installation progresses (verification → install scheduled → installing → live). Orders whose documents had a
  warning appear in **KYC reviews**; the order cannot pass "documents verified" until an ops user approves. Every
  document view and decision is written to the audit log.
* **Retention job.** Run daily (cron, Render cron job, GitHub Action, Supabase `pg_cron` calling an endpoint):
  `cd udyam/backend && .venv/bin/python -m app.jobs purge`. It deletes expired rejected/abandoned documents.
* **Migrations.** Change models, then `alembic revision --autogenerate -m "what changed"`, review the file, commit,
  `alembic upgrade head` on deploy. `alembic check` in CI tells you if models and migrations drifted.
* **Monitoring.** Logs are JSON lines with request ids and masked identifiers. `/api/health` returns 503 when the
  database is down (point your uptime monitor at it). Add Sentry for exceptions.
* **Tests.** `pytest` (SQLite) and `TEST_DATABASE_URL=postgresql://… pytest` (real Postgres) run the same 28 API and payment tests
  plus rules, advisor and KYC tests.

## 7. Before real customers (not done yet)

1. **Payments.** Razorpay is integrated and tested against a mocked API and forged-signature cases, but not yet against
   Razorpay's live servers; run a full test-mode payment (step 3.5) and then a small live payment before launch. Add
   refunds, reconciliation and GST invoices.
2. **Registries.** GSTIN and Udyam lookups read the case's mock files. Replace `registry.py` lookups with a licensed
   GST verification provider and the Udyam verification service.
3. **Install and activation.** Order steps are advanced by staff by hand. Connect your field-service and provisioning
   systems.
4. **Notifications.** Add WhatsApp/SMS/email status messages (the tracker already stores every event).
5. **Legal and security.** DPIA, privacy policy and terms, key rotation (KMS), a penetration test, rate limiting at
   the edge (Cloudflare), and a data-processing agreement with Supabase, Clerk and Google. Note: the free Gemini tier
   may use prompts to improve Google products, so move to the paid API for production.
6. **Accessibility and languages.** The conversation supports ten languages; the interface chrome is English only.
