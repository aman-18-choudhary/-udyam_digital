import React from "react";
import { inr } from "../api.js";

// All of the signed-in customer's orders, newest first. Paid orders open the live tracker;
// unpaid ones offer to finish the payment.
export default function Orders({ orders, loading, onTrack, onPay, onNew }) {
  return (
    <section className="card tilt">
      <div className="row between wrap">
        <div><h2>My orders</h2><p className="muted">Everything you have ordered, with live status.</p></div>
        <button className="btn" onClick={onNew}>Start a new order</button>
      </div>
      {loading && orders.length === 0 && <p className="muted">Loading your orders…</p>}
      {!loading && orders.length === 0 && <p className="muted">No orders yet. Start with the advisor and your orders will appear here.</p>}
      <ul className="orders">
        {orders.map((o) => {
          const unpaid = o.status === "PAYMENT_PENDING" || o.status === "PAYMENT_FAILED";
          return (
            <li key={o.id}>
              <div>
                <b>{o.business_name || "Your business"}</b>
                <small>{o.id} · placed {new Date(o.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</small>
                <small>{o.lines.length} product{o.lines.length === 1 ? "" : "s"} · {inr(o.monthly_total)}/month · pay today {inr(o.first_payment)}</small>
              </div>
              <div className="orders-right">
                <span className={`pill ${o.status === "ACTIVATED" ? "ok" : unpaid ? "warn" : ""}`}>{o.label}</span>
                {unpaid
                  ? <button className="btn small" onClick={() => onPay(o)}>Complete payment</button>
                  : <button className="btn ghost small" onClick={() => onTrack(o)}>Track</button>}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
