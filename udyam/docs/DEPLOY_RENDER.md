# Deploy to Render (one service, one URL)

The repository root has a `Dockerfile` that builds the React app and serves it together with the API from one
FastAPI process, and a `render.yaml` Blueprint. Data and files live in Supabase, so the service itself is stateless.

Plan: this repo is set to Render's **free** plan (`plan: free` in `render.yaml`). What that means:
* The service **sleeps after 15 minutes without traffic** and takes about a minute to wake on the next visit. Before
  a judge or demo, open the site a few minutes earlier. To stay awake, point a free uptime monitor
  (UptimeRobot, cron-job.org) at `https://<service>.onrender.com/api/health` every 5 minutes; one always-on service
  fits inside Render's 750 free hours a month.
* **512 MB RAM.** Enough for the API and one OCR at a time, but not for many simultaneous uploads. If you see
  out-of-memory restarts in the logs, switch to `plan: starter` (about US$7 a month).
* An order tracker open during a sleep reconnects by itself when the service wakes.

## 1. Put the code on GitHub
```bash
cd /Users/aman/Projects/Team_cracker
git add . && git commit -m "Project Udyam Digital"
# create an empty repository on github.com (private is fine), then:
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main && git push -u origin main
```
`.gitignore` keeps `.env`, the encryption key file, databases, uploads, the case brief and the organisers' specimen
documents out of the repository. Check the repo page afterwards: there must be no `.env` file.

## 2. Create the service
1. render.com → **New → Blueprint** → connect the GitHub repo. Render reads `render.yaml`.
2. It asks for every variable marked `sync: false`. Fill them from your local `udyam/backend/.env`, with these differences:
   * **`DATABASE_URL` must be the Supabase _Session pooler_ URI** (Supabase → Connect → Session pooler, port 5432).
     The direct `db.<ref>.supabase.co` host that works on your Mac is IPv6 only, and Render cannot reach it.
   * `VITE_CLERK_PUBLISHABLE_KEY` is used while the image is built; if you change it later, redeploy.
   * Leave `CLERK_AUTHORIZED_PARTIES` and `CORS_ORIGINS` empty for the first deploy; you fill them in step 3.
3. Deploy. The build takes a few minutes. The container applies database migrations, then starts the server.
   `GET https://<service>.onrender.com/api/health` should report `"db":"up"`, `"storage":"supabase"`,
   `"auth":"clerk"`, `"payments":"razorpay"`.

## 3. Tell the other services the new address
Replace `<url>` with `https://<service>.onrender.com`.
* **Render env:** `CLERK_AUTHORIZED_PARTIES=<url>` and `CORS_ORIGINS=<url>`; save to redeploy.
* **Razorpay → Webhooks:** edit the webhook URL to `<url>/api/webhooks/razorpay`. Keep the same secret as
  `RAZORPAY_WEBHOOK_SECRET`. Events: `payment.captured`, `payment.failed`, `order.paid`.
* **Clerk:** a development instance (`pk_test_…`) works on any URL but shows a "Development mode" banner, which is
  fine for a hackathon. For real customers create a **production** instance with your own domain.
* **Staff:** make sure your Clerk user has `{"role":"admin"}` in public metadata, so the staff console and the KYC
  review queue are visible on the live site.

## 4. Smoke test (about 5 minutes)
1. Open the URL in a private window, sign up as a new user.
2. Advisor → quote → upload the four documents of **one** specimen applicant (K03 is clean) → verify.
3. Pay with UPI id `success@razorpay`. The tracker should show "Payment received".
4. In the staff console (as admin): Orders → Advance until the order is live.
5. Check Razorpay → Webhooks → recent deliveries shows 200.

## 5. For the judges
* Keep `UDYAM_TODAY=2026-07-15` only while they test with the case's specimen documents (they are dated against
  that day). Remove it afterwards so real dates apply.
* Give them a test login (create a Clerk user) and a one-page note: the scenarios table in `udyam/README.md`.
* Payments run in Razorpay **test mode**: no money moves.

## If something fails
* Build fails at `npm ci`: the lockfile is missing from the repo (`udyam/frontend/package-lock.json` must be committed).
* App starts but `db` is `down`: `DATABASE_URL` is the direct host, not the session pooler, or the password has
  special characters that need URL-encoding.
* Sign-in page does not load: `VITE_CLERK_PUBLISHABLE_KEY` was empty at build time. Set it and redeploy.
* 401 on every call after sign-in: `CLERK_ISSUER` does not match the key's instance (copy the Frontend API URL again).
* Documents fail to upload: bucket `kyc-documents` missing or the service key is wrong (`/api/health` still says
  `supabase` because it only checks configuration, so test with an upload).
