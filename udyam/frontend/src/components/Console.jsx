import React, { useEffect, useState } from "react";
import { api, inr } from "../api.js";

const SEGMENTS = ["", "Micro retail & services", "Professional offices", "Small multi-site businesses", "Small manufacturers"];

export default function Console({ role }) {
  const ops = role === "ops" || role === "admin";
  const [tab, setTab] = useState("leads");
  const [funnel, setFunnel] = useState(null);
  const [model, setModel] = useState(null);
  const [leads, setLeads] = useState([]);
  const [segment, setSegment] = useState("");
  const [stage, setStage] = useState("Needs assessed");
  const [handoffs, setHandoffs] = useState([]);
  const [orders, setOrders] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [docs, setDocs] = useState({});
  const [msg, setMsg] = useState("");

  useEffect(() => { api.boFunnel().then(setFunnel); api.boModel().then(setModel); }, []);
  useEffect(() => {
    api.boLeads({ limit: 30, min_stage: stage, ...(segment ? { segment } : {}) }).then(setLeads);
  }, [segment, stage]);
  useEffect(() => {
    const load = () => { api.boHandoffs().then(setHandoffs); api.boOrders().then(setOrders); api.reviews().then(setReviews).catch(() => {}); };
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  const max = funnel ? funnel.counts[0] : 1;

  async function advance(id) {
    setMsg("");
    try { await api.advanceOrder(id); api.boOrders().then(setOrders); } catch (e) { setMsg(e.message); }
  }
  async function showDoc(cid, type) {
    try { const url = await api.reviewDocUrl(cid, type); setDocs((d) => ({ ...d, [`${cid}/${type}`]: url })); } catch (e) { setMsg(e.message); }
  }
  async function decide(cid, approve) {
    setMsg("");
    try { await api.reviewDecision(cid, approve); api.reviews().then(setReviews); } catch (e) { setMsg(e.message); }
  }

  return (
    <main className="stage">
      <div className="tabs" role="tablist">
        {[["leads", "Leads to call"], ["reviews", `KYC reviews (${reviews.length})`], ["orders", `Orders (${orders.length})`], ["handoffs", `Handoffs (${handoffs.length})`], ["funnel", "Funnel"]].map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === "funnel" && funnel && (
        <section className="card">
          <h2>Where the 5,000 leads go (Apr–Jun 2026)</h2>
          {funnel.stages.map((s, i) => (
            <div key={s} className="bar"><span>{s}</span><div><i style={{ width: `${(funnel.counts[i] / max) * 100}%` }} /></div><b>{funnel.counts[i].toLocaleString("en-IN")}</b></div>
          ))}
          {model && <p className="muted">Propensity model: {model.type}. Hold-out AUC on profile features alone is {model.holdout_auc_profile_only}. {model.note}</p>}
        </section>
      )}

      {tab === "leads" && (
        <section className="card">
          <div className="row between wrap">
            <div><h2>Leads the digital journey did not close</h2><p className="muted">Ranked by likelihood to activate if followed up. Each has a suggested next action from the reason they dropped.</p></div>
            <div className="row">
              <select value={stage} onChange={(e) => setStage(e.target.value)} aria-label="Minimum stage reached">
                {["Lead", "Contacted", "Needs assessed", "Quote accepted", "KYC complete"].map((s) => <option key={s}>{s}</option>)}
              </select>
              <select value={segment} onChange={(e) => setSegment(e.target.value)} aria-label="Segment">
                {SEGMENTS.map((s) => <option key={s} value={s}>{s || "All segments"}</option>)}
              </select>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Score</th><th>Business</th><th>Segment</th><th>Reached</th><th>Dropped because</th><th>Next action</th></tr></thead>
              <tbody>
                {leads.map((l) => (
                  <tr key={l.lead_id}>
                    <td><div className="score"><i style={{ width: `${l.score * 100}%` }} />{Math.round(l.score * 100)}</div></td>
                    <td><b>{l.business}</b><small>{l.city} · {l.source}{l.has_gstin ? " · GST" : ""}</small></td>
                    <td>{l.segment}</td><td>{l.stage_reached}</td><td>{l.drop_reason}</td><td>{l.next_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {msg && <p className="err" role="alert">{msg}</p>}

      {tab === "reviews" && (
        <section className="card">
          <h2>Documents waiting for a manual check</h2>
          {reviews.length === 0 ? <p className="muted">Nothing waiting.</p> : reviews.map((r) => (
            <div key={r.id} className="review">
              <div className="row between"><b>{r.id}</b><span className="muted">{new Date(r.created_at).toLocaleString("en-IN")}</span></div>
              <ul className="mini">{r.warnings.map((w, i) => <li key={i}><b>{w.label}:</b> {w.detail}</li>)}</ul>
              {ops && (<>
                <div className="row wrap">{r.documents.map((d) => <button key={d} className="btn ghost small" onClick={() => showDoc(r.id, d)}>View {d}</button>)}</div>
                <div className="docs">{r.documents.filter((d) => docs[`${r.id}/${d}`]).map((d) => <img key={d} src={docs[`${r.id}/${d}`]} alt={`${d} document`} />)}</div>
                <div className="row"><button className="btn" onClick={() => decide(r.id, true)}>Approve</button><button className="btn ghost" onClick={() => decide(r.id, false)}>Ask customer to fix</button></div>
              </>)}
            </div>
          ))}
          {!ops && <p className="muted small">Only the ops role can open documents and decide.</p>}
        </section>
      )}

      {tab === "handoffs" && (
        <section className="card">
          <h2>Customers who asked for a human</h2>
          {handoffs.length === 0 ? <p className="muted">None yet. Ask the advisor to "talk to a human" to see one appear here.</p> : (
            <ul className="mini">{handoffs.map((h, i) => <li key={i}>{new Date(h.at).toLocaleTimeString("en-IN")} · {h.profile?.biz_label || "business"} · {h.profile?.employees} people · Tier {h.profile?.city_tier} {h.profile?.city}</li>)}</ul>
          )}
        </section>
      )}

      {tab === "orders" && (
        <section className="card">
          <h2>Orders</h2>
          {orders.length === 0 ? <p className="muted">No orders yet.</p> : (
            <div className="table-wrap"><table>
              <thead><tr><th>Order</th><th>Business</th><th>Status</th><th>Monthly</th><th></th></tr></thead>
              <tbody>{orders.map((o) => <tr key={o.id}><td>{o.id}</td><td>{o.business}</td><td><span className="pill">{o.status}</span></td><td>{inr(o.monthly_total)}</td><td>{ops && o.can_advance && <button className="btn ghost small" onClick={() => advance(o.id)}>Advance</button>}</td></tr>)}</tbody>
            </table></div>
          )}
        </section>
      )}
    </main>
  );
}
