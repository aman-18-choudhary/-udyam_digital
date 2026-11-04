import React, { useEffect, useRef, useState } from "react";
import { api, inr } from "../api.js";
import Counter from "./Counter.jsx";

export default function Advisor({ lang, sessionId, setSessionId, onProfile, onRec, onCheckout, orders = 0, onOrders }) {
  const [msgs, setMsgs] = useState([]);
  const [chips, setChips] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState(null);
  const [err, setErr] = useState("");
  const end = useRef(null);

  const begin = () => {
    setErr("");
    api.start(lang).then((r) => {
      setSessionId(r.session_id);
      setMsgs([{ who: "bot", text: r.reply }]);
      setChips(r.chips || []);
    }).catch((e) => setErr(e.message));
  };
  useEffect(() => { if (!sessionId) begin(); }, []); // eslint-disable-line

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy]);

  async function send(t) {
    const value = (t ?? text).trim();
    if (!value || busy || !sessionId) return;
    setText(""); setChips([]); setErr("");
    setMsgs((m) => [...m, { who: "me", text: value }]);
    setBusy(true);
    try {
      const r = await api.message(sessionId, value);
      setMsgs((m) => [...m, { who: "bot", text: r.reply }]);
      setChips(r.chips || []);
      onProfile(r.profile || {});
      if (r.recommendation) {
        setRec(r.recommendation);
        onRec(r.recommendation, r.profile, null);
      }
      if (r.action === "checkout" && r.recommendation) onCheckout(r.recommendation);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid2">
      <section className="card chat" aria-label="Advisor chat">
        <div className="chat-log" role="log" aria-live="polite">
          {msgs.map((m, i) => (
            <div key={i} className={`bubble ${m.who}`}>{m.text}</div>
          ))}
          {(busy || (!sessionId && !err)) && <div className="bubble bot typing"><i /><i /><i /></div>}
          <div ref={end} />
        </div>
        {err && <p className="err" role="alert">{err}{!sessionId && <> <button className="link" onClick={begin}>Try again</button></>}</p>}
        <div className="chips">
          {chips.map((c) => <button key={c} className="chip" onClick={() => send(c)} disabled={busy}>{c}</button>)}
        </div>
        <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your answer…" maxLength={500} aria-label="Your answer" disabled={busy} />
          <button className="btn" disabled={busy || !text.trim()}>Send</button>
        </form>
      </section>

      <aside className="card side tilt">
        {orders > 0 && (
          <div className="orders-hint">
            <div><b>You have {orders} order{orders === 1 ? "" : "s"}</b><small>Track status or finish a payment</small></div>
            <button className="btn ghost small" onClick={onOrders}>My orders</button>
          </div>
        )}
        {!rec ? (
          <>
            <h3>How it works</h3>
            <ol className="how">
              <li>Answer 5 quick questions</li>
              <li>Get a bundle with one clear monthly price</li>
              <li>Verify documents in minutes, not days</li>
              <li>Track installation live</li>
            </ol>
            <p className="muted">Prices and eligibility come from the Accel catalogue rules, never guessed by the AI.</p>
          </>
        ) : (
          <>
            <h3>Your bundle</h3>
            <p className="muted">{rec.segment_label}</p>
            <ul className="mini">
              {rec.items.filter((i) => i.included).map((i) => (
                <li key={i.product_id}><span>{i.name}{i.qty > 1 ? ` × ${i.qty}` : ""}</span></li>
              ))}
            </ul>
            <div className="big"><Counter value={rec.quote.monthly_total} /><small>/month incl. GST</small></div>
            <p className="muted">+ {inr(rec.quote.setup_total)} one-time setup · live in about {rec.quote.install_days} days</p>
            {rec.saving_with_24_months > 0 && rec.term === 12 && (
              <p className="note">Save about {inr(rec.saving_with_24_months)}/month with a 24-month term.</p>
            )}
            {rec.excluded.length > 0 && (
              <details><summary>Not available for you ({rec.excluded.length})</summary>
                <ul className="mini">{rec.excluded.map((e, i) => <li key={i}>{e.reason}</li>)}</ul>
              </details>
            )}
            <button className="btn wide" onClick={() => onCheckout(rec)}>Review quote & continue</button>
          </>
        )}
      </aside>
    </div>
  );
}
