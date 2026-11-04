import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, inr } from "../api.js";
import Counter from "./Counter.jsx";

export default function Quote({ sessionId, rec, bundle, setBundle, caseId, onBack, onNext }) {
  const [quote, setQuote] = useState(null);
  const [problems, setProblems] = useState([]);
  const [cat, setCat] = useState([]);
  const [adding, setAdding] = useState("");
  const timer = useRef(null);

  const meta = useMemo(() => {
    const m = {};
    (rec?.items || []).forEach((i) => (m[i.product_id] = i));
    cat.forEach((c) => { m[c.id] = { ...(m[c.id] || {}), name: c.name, unit: c.unit, why: m[c.id]?.why || c.description, role: m[c.id]?.role || "optional" }; });
    return m;
  }, [rec, cat]);

  useEffect(() => { api.catalogue(sessionId).then(setCat).catch(() => {}); }, [sessionId]);

  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const r = await api.quote({ session_id: sessionId, items: bundle.items, term: bundle.term, kyc_case_id: caseId });
      setProblems(r.problems);
      setQuote(r.quote);
    }, 200);
    return () => clearTimeout(timer.current);
  }, [bundle, sessionId, caseId]);

  const update = (pid, patch) => setBundle((b) => ({ ...b, items: b.items.map((i) => (i.product_id === pid ? { ...i, ...patch } : i)) }));
  const addable = cat.filter((c) => c.eligible_standalone && !bundle.items.some((i) => i.product_id === c.id));
  const probFor = (pid) => problems.find((p) => p.product_id === pid);

  return (
    <div className="grid2">
      <section className="card">
        <div className="row between">
          <h2>Build your bundle</h2>
          <div className="seg" role="group" aria-label="Commitment">
            {[12, 24].map((t) => (
              <button key={t} className={bundle.term === t ? "on" : ""} onClick={() => setBundle((b) => ({ ...b, term: t }))}>{t} months</button>
            ))}
          </div>
        </div>
        <ul className="lines">
          {bundle.items.map((it) => {
            const m = meta[it.product_id] || {};
            const line = quote?.lines.find((l) => l.product_id === it.product_id);
            const prob = probFor(it.product_id);
            return (
              <li key={it.product_id} className={`${it.included ? "" : "off"} ${prob ? "bad" : ""}`}>
                <label className="tick">
                  <input type="checkbox" checked={it.included} onChange={(e) => update(it.product_id, { included: e.target.checked })} />
                  <span>
                    <b>{m.name || it.product_id}</b>
                    <small>{m.why}</small>
                    {prob && <em className="err">{prob.message}</em>}
                  </span>
                </label>
                <div className="qty" aria-label={`Quantity of ${m.name}`}>
                  <button onClick={() => update(it.product_id, { qty: Math.max(1, it.qty - 1) })} disabled={!it.included}>−</button>
                  <output>{it.qty}</output>
                  <button onClick={() => update(it.product_id, { qty: Math.min(50, it.qty + 1) })} disabled={!it.included}>+</button>
                </div>
                <div className="price">{line ? inr(line.monthly) : "—"}<small>{m.unit ? `per ${m.unit.replace("per ", "")}` : ""}</small></div>
              </li>
            );
          })}
        </ul>
        {addable.length > 0 && (
          <div className="row">
            <select value={adding} onChange={(e) => setAdding(e.target.value)} aria-label="Add another product">
              <option value="">Add another product…</option>
              {addable.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.category})</option>)}
            </select>
            <button className="btn ghost" disabled={!adding} onClick={() => { setBundle((b) => ({ ...b, items: [...b.items, { product_id: adding, qty: 1, included: true }] })); setAdding(""); }}>Add</button>
          </div>
        )}
        {rec?.excluded?.length > 0 && (
          <details className="why-not"><summary>Why some products are not offered</summary>
            <ul>{rec.excluded.map((e, i) => <li key={i}>{e.reason}</li>)}</ul>
          </details>
        )}
      </section>

      <aside className="card side sticky tilt">
        <h3>Your price</h3>
        {quote ? (
          <>
            <div className="big"><Counter value={quote.monthly_total} /><small>/month incl. GST</small></div>
            <dl className="totals">
              <div><dt>Monthly (before GST)</dt><dd>{inr(quote.monthly_subtotal)}</dd></div>
              <div><dt>GST 18%</dt><dd>{inr(quote.monthly_gst)}</dd></div>
              <div><dt>One-time setup (incl. GST)</dt><dd>{inr(quote.setup_total)}</dd></div>
              <div className="strong"><dt>Pay today</dt><dd>{inr(quote.first_payment)}</dd></div>
            </dl>
            <p className="muted">Live in about {quote.install_days} days after verification.{quote.bundle_discount_applied ? " Bundle discount applied." : ""}</p>
            <details><summary>How the price is set</summary><p className="muted">{quote.pricing_note}</p></details>
          </>
        ) : (
          <p className="muted">{problems[0]?.message || (bundle.items.some((i) => i.included) ? "Calculating…" : "Pick at least one product.")}</p>
        )}
        {problems.length > 0 && <p className="err" role="alert">Fix the highlighted items to continue.</p>}
        <div className="row">
          <button className="btn ghost" onClick={onBack}>Back</button>
          <button className="btn grow" disabled={!quote || problems.length > 0} onClick={onNext}>Verify documents</button>
        </div>
      </aside>
    </div>
  );
}
