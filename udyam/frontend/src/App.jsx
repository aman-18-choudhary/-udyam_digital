import React, { useEffect, useState } from "react";
import { SignedIn, SignedOut, SignIn, UserButton, useAuth } from "@clerk/clerk-react";
import { api, setTokenGetter } from "./api.js";
import Advisor from "./components/Advisor.jsx";
import Quote from "./components/Quote.jsx";
import Kyc from "./components/Kyc.jsx";
import Pay from "./components/Pay.jsx";
import Tracker from "./components/Tracker.jsx";
import Console from "./components/Console.jsx";

const STAGES = [["advise", "Advise"], ["quote", "Quote"], ["kyc", "Verify"], ["pay", "Pay"], ["track", "Track"]];
const LANGS = { en: "English", hi: "हिन्दी", mr: "मराठी", ta: "தமிழ்", te: "తెలుగు", bn: "বাংলা", gu: "ગુજરાતી", kn: "ಕನ್ನಡ", ml: "മലയാളം", pa: "ਪੰਜਾਬੀ" };

// Registers Clerk's token getter for the API client, then renders children once it is in place.
function WithClerkToken({ children }) {
  const { getToken, isLoaded } = useAuth();
  const [ready, setReady] = useState(false);
  useEffect(() => { setTokenGetter(() => getToken()); setReady(true); }, [getToken]);
  return isLoaded && ready ? children : <p className="muted pad">Loading…</p>;
}

export default function App({ clerk = false }) {
  const [cfg, setCfg] = useState(null);
  useEffect(() => { api.config().then(setCfg).catch(() => setCfg({ offline: true, llm: {} })); }, []);

  if (!cfg) return <p className="muted pad">Loading…</p>;
  if (cfg.auth_required && !clerk) {
    return (
      <div className="shell"><main className="stage"><section className="card narrow">
        <h2>Sign-in is not configured</h2>
        <p>The API requires sign-in but the web app has no Clerk key. Set <code>VITE_CLERK_PUBLISHABLE_KEY</code> in <code>frontend/.env</code> and rebuild.</p>
      </section></main></div>
    );
  }
  if (!cfg.auth_required) return <Journey cfg={cfg} clerk={false} />;
  return (
    <>
      <SignedOut>
        <div className="shell">
          <header className="top"><div className="brand"><span className="logo">a</span><div><b>Udyam Digital</b><small>Accel Business for small businesses</small></div></div></header>
          <main className="stage signin">
            <div>
              <h1>Get your business online in one sitting</h1>
              <p className="muted">Sign in to get a recommendation, a clear price and fast verification. Your documents stay private and you can delete them any time.</p>
            </div>
            <SignIn routing="hash" />
          </main>
        </div>
      </SignedOut>
      <SignedIn>
        <WithClerkToken><Journey cfg={cfg} clerk /></WithClerkToken>
      </SignedIn>
    </>
  );
}

function Journey({ cfg, clerk }) {
  const [route, setRoute] = useState(location.hash === "#/console" ? "console" : "app");
  const [me, setMe] = useState(null);
  const [lang, setLang] = useState("en");
  const [stage, setStage] = useState("advise");
  const [sessionId, setSessionId] = useState(null);
  const [profile, setProfile] = useState({});
  const [rec, setRec] = useState(null);
  const [bundle, setBundle] = useState({ items: [], term: 12 });
  const [caseId, setCaseId] = useState(null);
  const [kycStatus, setKycStatus] = useState(null);
  const [order, setOrder] = useState(null);
  const [myOrders, setMyOrders] = useState([]);

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
    api.myOrders().then(setMyOrders).catch(() => {});
    const on = () => setRoute(location.hash === "#/console" ? "console" : "app");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const reached = STAGES.findIndex(([k]) => k === stage);
  const restart = () => {
    setSessionId(null); setProfile({}); setRec(null); setBundle({ items: [], term: 12 });
    setCaseId(null); setKycStatus(null); setOrder(null); setStage("advise");
    api.myOrders().then(setMyOrders).catch(() => {});
  };
  const staff = !!me?.staff;

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <span className="logo">a</span>
          <div><b>Udyam Digital</b><small>Accel Business for small businesses</small></div>
        </div>
        <div className="top-right">
          <span className={`pill ${cfg.llm?.configured ? "ok" : "warn"}`} title={cfg.llm?.configured ? "Gemini is answering" : "Basic mode: English and Hindi only."}>
            {cfg.offline ? "API offline" : cfg.llm?.configured ? "AI: Gemini" : "AI: basic mode"}
          </span>
          {!cfg.auth_required && <span className="pill warn" title="The API has no sign-in. Local development only.">Auth off (dev)</span>}
          <select value={lang} disabled={stage !== "advise" || !!sessionId} onChange={(e) => setLang(e.target.value)} aria-label="Language">
            {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {staff && <a className="link" href={route === "console" ? "#/" : "#/console"}>{route === "console" ? "Customer view" : "Staff console"}</a>}
          {clerk && <UserButton />}
        </div>
      </header>

      {route === "console" && staff ? (
        <Console role={me?.role} />
      ) : (
        <>
          <nav className="steps" aria-label="Progress">
            {STAGES.map(([k, label], i) => (
              <div key={k} className={`step ${i < reached ? "done" : ""} ${i === reached ? "now" : ""}`}>
                <span>{i < reached ? "✓" : i + 1}</span>{label}
              </div>
            ))}
          </nav>
          {stage === "advise" && !sessionId && myOrders.length > 0 && (
            <section className="stage" style={{ paddingBottom: 0 }}>
              <div className="card">
                <h3>Your orders</h3>
                <ul className="mini">
                  {myOrders.map((o) => (
                    <li key={o.id} className="row between"><span>{o.business_name || o.id} · <b>{o.label}</b></span>
                      <button className="link" onClick={() => { setOrder(o); setStage("track"); }}>Track</button></li>
                  ))}
                </ul>
              </div>
            </section>
          )}
          <main className="stage">
            {stage === "advise" && (
              <Advisor lang={lang} sessionId={sessionId} setSessionId={setSessionId}
                onProfile={setProfile} onRec={(r, p) => { setRec(r); setProfile(p); }}
                onCheckout={(r) => { setBundle({ items: r.items.map((i) => ({ product_id: i.product_id, qty: i.qty, included: i.included })), term: r.term }); setStage("quote"); }} />
            )}
            {stage === "quote" && <Quote sessionId={sessionId} rec={rec} bundle={bundle} setBundle={setBundle} caseId={caseId} onBack={() => setStage("advise")} onNext={() => setStage("kyc")} />}
            {stage === "kyc" && (
              <Kyc sessionId={sessionId} caseId={caseId} setCaseId={setCaseId} setKycStatus={setKycStatus} kycStatus={kycStatus}
                demo={cfg.demo} onBack={() => setStage("quote")} onNext={() => setStage("pay")} />
            )}
            {stage === "pay" && <Pay sessionId={sessionId} caseId={caseId} bundle={bundle} order={order} setOrder={setOrder} demo={cfg.demo} payments={cfg.payments} onBack={() => setStage("kyc")} onPaid={() => setStage("track")} />}
            {stage === "track" && <Tracker order={order} onRestart={restart} />}
          </main>
        </>
      )}
      <footer className="foot">
        {cfg.demo ? "Demo mode: sample applicants and simulated bank declines are enabled. " : ""}{cfg.payments?.provider === "razorpay" ? "Payments are processed by Razorpay." : "Payments are in test mode (no money moves); connect Razorpay for real payments."}
      </footer>
    </div>
  );
}
