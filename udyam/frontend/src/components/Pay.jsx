import React, { useEffect, useState } from "react";
import { api, inr } from "../api.js";
import { openCheckout } from "./razorpay.js";

export default function Pay({ sessionId, caseId, bundle, order, setOrder, demo, payments, onBack, onPaid }) {
  const online = payments?.provider === "razorpay";
  const [err, setErr] = useState("");
  const [method, setMethod] = useState("upi");
  const [fail, setFail] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (order) return;
    api.order({ session_id: sessionId, kyc_case_id: caseId, items: bundle.items, term: bundle.term })
      .then(setOrder).catch((e) => setErr(e.message));
  }, []); // eslint-disable-line

  async function pay() {
    setBusy(true); setErr("");
    try {
      if (online) {
        const intent = await api.paymentIntent(order.id);
        const r = await openCheckout(intent);
        const o = await api.verifyPayment(order.id, r);
        setOrder(o);
        onPaid();
      } else {
        const o = await api.pay(order.id, { method, simulate_failure: fail });
        setOrder(o);
        if (o.status === "PAYMENT_FAILED") { setErr("The bank declined the payment (test mode). Untick the decline option and retry."); setFail(false); }
        else onPaid();
      }
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <section className="card narrow tilt">
      <h2>Review and pay</h2>
      {!order ? (err ? <p className="err" role="alert">{err}</p> : <p className="muted">Preparing your order…</p>) : (
        <>
          <p className="muted">{order.business_name || "Your business"} · Order {order.id}</p>
          <ul className="lines compact">
            {order.lines.map((l) => (
              <li key={l.product_id}><span><b>{l.name}</b><small>{l.qty} × {inr(l.unit_price)} · {l.contract_months} month term</small></span><span className="price">{inr(l.monthly)}</span></li>
            ))}
          </ul>
          <dl className="totals">
            <div><dt>Monthly from next cycle</dt><dd>{inr(order.monthly_total)}</dd></div>
            <div className="strong"><dt>Pay today (first month + setup, incl. GST)</dt><dd>{inr(order.first_payment)}</dd></div>
          </dl>
          {!online && <fieldset className="methods"><legend>Payment method (test mode, no money is charged)</legend>
            {[["upi", "UPI"], ["card", "Card"], ["netbanking", "Net banking"]].map(([k, l]) => (
              <label key={k} className={method === k ? "on" : ""}><input type="radio" name="m" checked={method === k} onChange={() => setMethod(k)} />{l}</label>
            ))}
          </fieldset>}
          {online && <p className="muted small">You will pay securely on Razorpay (UPI, cards, net banking). We never see your card or UPI details.</p>}
          {demo && !online && <label className="tick"><input type="checkbox" checked={fail} onChange={(e) => setFail(e.target.checked)} /><span>Simulate a bank decline (to see how a failed payment is handled)</span></label>}
          {err && <p className="err" role="alert">{err}</p>}
          <div className="row">
            <button className="btn ghost" onClick={onBack} disabled={busy}>Back</button>
            <button className="btn grow" onClick={pay} disabled={busy}>{busy ? "Processing…" : `Pay ${inr(order.first_payment)}`}</button>
          </div>
        </>
      )}
    </section>
  );
}
