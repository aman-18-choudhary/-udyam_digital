import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const SLOTS = [
  ["gst", "GST certificate"],
  ["udyam", "Udyam certificate"],
  ["id", "Signatory ID"],
  ["address", "Address proof"],
];
const ICON = { pass: "✓", warn: "!", fail: "✕", info: "i", limit: "!" };

function summarise(doc) {
  const f = doc?.fields || {};
  const bits = [f.trade_name || f.enterprise_name || f.name || f.billed_to, f.gstin || f.udyam_number, f.bill_date && `bill ${f.bill_date}`, f.valid_till && `valid till ${f.valid_till}`].filter(Boolean);
  return bits.join(" · ");
}

export default function Kyc({ sessionId, caseId, setCaseId, kycStatus, setKycStatus, demo, onBack, onNext }) {
  const [notice, setNotice] = useState(null);
  const [agree, setAgree] = useState(false);
  const [consented, setConsented] = useState(!!caseId);
  const [docs, setDocs] = useState({});
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);
  const [specimens, setSpecimens] = useState([]);
  const [gstin, setGstin] = useState("");
  const [look, setLook] = useState(null);

  useEffect(() => { api.notice().then(setNotice); if (demo) api.specimens().then(setSpecimens).catch(() => {}); }, []);

  async function giveConsent() {
    setErr(""); setBusy("consent");
    try {
      await api.consent(sessionId, notice.version);
      const c = await api.openCase(sessionId, look?.found ? gstin.toUpperCase() : null);
      setCaseId(c.id); setConsented(true);
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  }

  async function doLookup() {
    setErr("");
    try { setLook((await api.lookup({ gstin })).gstin); } catch (e) { setErr(e.message); }
  }

  async function upload(type, file) {
    if (!file) return;
    setErr(""); setBusy(type); setResult(null);
    try {
      const r = await api.upload(caseId, file, type);
      setDocs((d) => ({ ...d, [type]: r.document }));
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  }

  async function useSpecimen(applicant) {
    if (!applicant) return;
    setErr(""); setBusy("specimen"); setResult(null);
    try {
      const r = await api.specimen(caseId, applicant);
      const next = {};
      r.documents.forEach((d) => { if (d.doc_type) next[d.doc_type] = d; });
      setDocs(next);
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  }

  async function verify() {
    setErr(""); setBusy("verify");
    try {
      const c = await api.verify(caseId);
      setResult(c.result); setKycStatus(c.status);
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  }

  async function withdraw() {
    if (!confirm("Withdraw consent and delete all uploaded documents?")) return;
    await api.withdraw(sessionId);
    setCaseId(null); setConsented(false); setDocs({}); setResult(null); setKycStatus(null); setAgree(false);
  }

  if (!consented) {
    return (
      <section className="card narrow">
        <h2>{notice?.title || "Your documents, your choice"}</h2>
        {notice && (
          <>
            <p>{notice.purpose}</p>
            <dl className="notice">
              <dt>What we collect</dt><dd>{notice.collected.join(", ")}</dd>
              <dt>Not used for</dt><dd>{notice.not_used_for}</dd>
              <dt>How we protect it</dt><dd>{notice.protection}</dd>
              <dt>How long we keep it</dt><dd>{notice.retention}</dd>
              <dt>Your rights</dt><dd>{notice.rights}</dd>
            </dl>
            <div className="lookup">
              <label>Have a GSTIN? Check it first and we will pre-fill what we can
                <span className="row"><input value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} placeholder="15-character GSTIN" maxLength={15} />
                  <button className="btn ghost" onClick={doLookup} disabled={gstin.length !== 15}>Check</button></span>
              </label>
              {look && (look.found
                ? <p className={look.status === "Active" ? "okmsg" : "err"}>{look.trade_name} ({look.masked}): {look.status}</p>
                : <p className="err">{look.valid_format ? "Not found in the registry." : "That GSTIN is not valid."}</p>)}
            </div>
            <label className="tick agree"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
              <span>I agree to Accel using these documents to verify my business, as described above.</span></label>
            {err && <p className="err" role="alert">{err}</p>}
            <div className="row">
              <button className="btn ghost" onClick={onBack}>Back</button>
              <button className="btn grow" disabled={!agree || busy === "consent"} onClick={giveConsent}>Agree and continue</button>
            </div>
          </>
        )}
      </section>
    );
  }

  return (
    <div className="grid2">
      <section className="card">
        <div className="row between">
          <h2>Verify your business</h2>
          <button className="link" onClick={withdraw}>Withdraw consent & delete</button>
        </div>
        <p className="muted">Take a photo or upload each document. We read it on our servers; nothing is sent to an AI model.</p>
        <div className="slots">
          {SLOTS.map(([k, label]) => {
            const d = docs[k];
            const bad = d?.issues?.length > 0;
            return (
              <div key={k} className={`slot ${d ? (bad ? "warn" : "ok") : ""}`}>
                <div className="row between"><b>{label}</b>{d && <span className="tag">{bad ? "check" : "read"}</span>}</div>
                {d ? <p className="muted">{summarise(d) || "Received"}</p> : <p className="muted">Not uploaded yet</p>}
                {d?.issues?.map((i, n) => <p key={n} className="err small">{i.message}</p>)}
                {d?.quality?.deskewed && <p className="muted small">Straightened automatically.</p>}
                <label className="btn ghost small">
                  {busy === k ? "Reading…" : d ? "Replace" : "Upload / take photo"}
                  <input type="file" accept="image/png,image/jpeg" capture="environment" hidden onChange={(e) => upload(k, e.target.files[0])} disabled={!!busy} />
                </label>
              </div>
            );
          })}
        </div>
        {demo && <div className="row sample">
          <select defaultValue="" onChange={(e) => { useSpecimen(e.target.value); e.target.value = ""; }} disabled={!!busy} aria-label="Load a sample applicant">
            <option value="">Try a sample applicant…</option>
            {specimens.map((s) => <option key={s.id} value={s.id}>{s.id} ({s.documents.length} documents)</option>)}
          </select>
          {busy === "specimen" && <span className="muted">Reading documents…</span>}
        </div>}
        {err && <p className="err" role="alert">{err}</p>}
        <button className="btn wide" onClick={verify} disabled={busy === "verify" || Object.keys(docs).length === 0}>
          {busy === "verify" ? "Checking…" : "Verify documents"}
        </button>
      </section>

      <aside className="card side">
        <h3>Result</h3>
        {!result ? <p className="muted">Upload your documents, then press Verify. We check the numbers against the GST and Udyam registers, names, addresses and dates.</p> : (
          <>
            <div className={`banner ${result.decision}`}>
              {result.decision === "verified" && "Verified. You can continue."}
              {result.decision === "review" && "Almost there. A quick manual check will run in the background; you can continue."}
              {result.decision === "action_required" && "We need a few fixes before we can continue."}
            </div>
            {result.restrictions?.includes("gst") && result.decision !== "action_required" && (
              <p className="note warnnote">Your GST registration is not active, so products that need GST are not available. You can continue with the others, or <button className="link" onClick={onBack}>adjust your bundle</button>.</p>
            )}
            <ul className="checks">
              {result.checks.map((c, i) => (
                <li key={i} className={c.status}>
                  <span className="ico">{ICON[c.status]}</span>
                  <div><b>{c.label}</b><small>{c.detail}</small>{c.fix && c.status !== "pass" && <em>{c.fix}</em>}</div>
                </li>
              ))}
            </ul>
          </>
        )}
        <div className="row">
          <button className="btn ghost" onClick={onBack}>Back</button>
          <button className="btn grow" disabled={!["verified", "review"].includes(kycStatus)} onClick={onNext}>Continue to payment</button>
        </div>
      </aside>
    </div>
  );
}
