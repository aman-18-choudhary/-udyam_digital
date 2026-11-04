import React, { useEffect, useState } from "react";
import { inr, streamOrder } from "../api.js";

const STEP_LABEL = {
  PAYMENT_CONFIRMED: "Payment received",
  KYC_VERIFIED: "Documents verified",
  INSTALL_SCHEDULED: "Installation scheduled",
  INSTALLING: "Installing at your site",
  ACTIVATED: "Services live",
};

export default function Tracker({ order: initial, onRestart }) {
  const [order, setOrder] = useState(initial);
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!initial) return undefined;
    return streamOrder(initial.id, setOrder, setLive);
  }, [initial?.id]); // eslint-disable-line

  if (!order) return null;
  const seen = new Set(order.events.map((e) => e.status));
  const done = order.status === "ACTIVATED";
  const review = seen.has("KYC_REVIEW") && !seen.has("KYC_VERIFIED");
  const evOf = (s) => order.events.find((e) => e.status === s);

  return (
    <section className="card narrow">
      <div className="row between">
        <h2>{done ? "You are live!" : "Tracking your order"}</h2>
        <span className={`pill ${live && !done ? "ok" : ""}`}>{done ? "Complete" : live ? "● Live" : "Reconnecting…"}</span>
      </div>
      <p className="muted">{order.business_name} · {order.id} · {inr(order.monthly_total)}/month · expected by {new Date(order.install_by).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</p>
      {review && <p className="note warnnote">{evOf("KYC_REVIEW")?.note}</p>}
      <ol className="timeline">
        {order.steps.map((s) => {
          const e = evOf(s);
          const isNext = !seen.has(s) && order.steps.find((x) => !seen.has(x)) === s;
          return (
            <li key={s} className={e ? "done" : isNext ? "next" : ""}>
              <span className="dot">{e ? "✓" : ""}</span>
              <div><b>{STEP_LABEL[s]}</b>
                <small>{e ? `${e.note} · ${new Date(e.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : isNext ? "In progress…" : "Pending"}</small></div>
            </li>
          );
        })}
      </ol>
      <div className="row"><button className="btn ghost" onClick={onRestart}>{done ? "Start another journey" : "Back to start"}</button></div>
      <p className="muted small">No need to call support. This page updates by itself.</p>
    </section>
  );
}
