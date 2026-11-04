import React, { useEffect, useState } from "react";
import { SignedIn, SignedOut, SignIn, UserButton, useAuth } from "@clerk/clerk-react";
import { api, setTokenGetter } from "./api.js";
import Advisor from "./components/Advisor.jsx";
import Quote from "./components/Quote.jsx";
import Kyc from "./components/Kyc.jsx";
import Pay from "./components/Pay.jsx";
import Tracker from "./components/Tracker.jsx";
import Console from "./components/Console.jsx";
import Orders from "./components/Orders.jsx";
import Backdrop from "./components/Backdrop.jsx";
import useTilt from "./components/useTilt.js";

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
  // dev only (stripped from production builds): #/landing shows the signed-out page without signing out
  if (import.meta.env.DEV && location.hash === "#/landing") return <Landing preview />;
  if (!cfg.auth_required) return <Journey cfg={cfg} clerk={false} />;
  return (
    <>
      <SignedOut>
        <Landing />
      </SignedOut>
      <SignedIn>
        <WithClerkToken><Journey cfg={cfg} clerk /></WithClerkToken>
      </SignedIn>
    </>
  );
}

function Landing({ preview = false }) {
  useTilt();
  return (
    <div className="shell landing">
      <Backdrop variant="hero" />
      <header className="top">
        <div className="brand"><span className="logo">a</span><div><b>Udyam Digital</b><small>Accel Business for small businesses</small></div></div>
      </header>
      <main className="hero">
        <div className="hero-copy stage-in">
          <span className="eyebrow">Airtel Sync 2026 · Project Udyam</span>
          <h1>Get your business <em>online</em> in one sitting</h1>
          <p className="lead">Tell us about your shop, clinic or workshop. Get the right internet, phone and security bundle at one clear price, verify in minutes and track installation live. No sales visits, no paperwork queues.</p>
          <div className="features">
            <div className="card tilt feature"><b>5</b><span>questions to a recommended bundle</span></div>
            <div className="card tilt feature"><b>4</b><span>documents, read and checked in seconds</span></div>
            <div className="card tilt feature"><b>0</b><span>sales visits needed to get started</span></div>
          </div>
          <ul className="proof">
            <li>Hindi and 9 more languages</li><li>GST and Udyam check</li><li>UPI and card payments</li><li>Live order tracking</li><li>Delete your documents any time</li>
          </ul>
        </div>
        <div className="hero-auth">{preview ? <div className="card" style={{ width: "min(380px, 100%)", height: 420, display: "grid", placeItems: "center" }}>Clerk sign-in card (dev preview)</div> : <SignIn routing="hash" />}</div>
      </main>
      <footer className="foot">Synthetic data for the Airtel Sync 2026 case. Payments run in test mode.</footer>
    </div>
  );
}

function Journey({ cfg, clerk }) {
  useTilt();
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
  const [view, setView] = useState("journey");   // journey | orders
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [fromOrders, setFromOrders] = useState(false);

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
    api.myOrders().then(setMyOrders).catch(() => {});
    const on = () => setRoute(location.hash === "#/console" ? "console" : "app");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const loadOrders = () => { setOrdersLoading(true); return api.myOrders().then(setMyOrders).catch(() => {}).finally(() => setOrdersLoading(false)); };
  const openOrders = () => { setView("orders"); loadOrders(); };
  const goTrack = (o) => { setOrder(o); setFromOrders(true); setStage("track"); setView("journey"); };
  const goPay = (o) => { setOrder(o); setFromOrders(true); setStage("pay"); setView("journey"); };
  const reached = STAGES.findIndex(([k]) => k === stage);
  const restart = () => {
    setSessionId(null); setProfile({}); setRec(null); setBundle({ items: [], term: 12 });
    setCaseId(null); setKycStatus(null); setOrder(null); setFromOrders(false); setStage("advise");
    loadOrders();
  };
  const staff = !!me?.staff;

  return (
    <div className="shell">
      <Backdrop variant="ambient" />
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
          <button className="link" onClick={() => (view === "orders" ? setView("journey") : openOrders())}>{view === "orders" ? "Back to journey" : `My orders${myOrders.length ? ` (${myOrders.length})` : ""}`}</button>
          {staff && <a className="link" href={route === "console" ? "#/" : "#/console"}>{route === "console" ? "Customer view" : "Staff console"}</a>}
          {clerk && <UserButton />}
        </div>
      </header>

      {route === "console" && staff ? (
        <Console role={me?.role} />
      ) : (
        <>
          {view === "orders" && (
            <main className="stage stage-in"><Orders orders={myOrders} loading={ordersLoading} onTrack={goTrack} onPay={goPay} onNew={() => { restart(); setView("journey"); }} /></main>
          )}
          <div hidden={view === "orders"}>
          <nav className="steps" aria-label="Progress">
            {STAGES.map(([k, label], i) => (
              k === "track" && stage !== "track" && myOrders.length > 0 ? (
                <button key={k} className="step clickable" onClick={openOrders} title="See and track your orders">
                  <span>{i + 1}</span>{label} ({myOrders.length})
                </button>
              ) : (
                <div key={k} className={`step ${i < reached ? "done" : ""} ${i === reached ? "now" : ""}`}>
                  <span>{i < reached ? "✓" : i + 1}</span>{label}
                </div>
              )
            ))}
          </nav>
          <main className="stage stage-in">
            {stage === "advise" && (
              <Advisor lang={lang} sessionId={sessionId} setSessionId={setSessionId}
                onProfile={setProfile} onRec={(r, p) => { setRec(r); setProfile(p); }} orders={myOrders.length} onOrders={openOrders}
                onCheckout={(r) => { setBundle({ items: r.items.map((i) => ({ product_id: i.product_id, qty: i.qty, included: i.included })), term: r.term }); setStage("quote"); }} />
            )}
            {stage === "quote" && <Quote sessionId={sessionId} rec={rec} bundle={bundle} setBundle={setBundle} caseId={caseId} onBack={() => setStage("advise")} onNext={() => setStage("kyc")} />}
            {stage === "kyc" && (
              <Kyc sessionId={sessionId} caseId={caseId} setCaseId={setCaseId} setKycStatus={setKycStatus} kycStatus={kycStatus}
                demo={cfg.demo} onBack={() => setStage("quote")} onNext={() => setStage("pay")} />
            )}
            {stage === "pay" && <Pay sessionId={sessionId} caseId={caseId} bundle={bundle} order={order} setOrder={setOrder} demo={cfg.demo} payments={cfg.payments} onBack={() => (fromOrders ? openOrders() : setStage("kyc"))} onPaid={() => { setStage("track"); loadOrders(); }} />}
            {stage === "track" && <Tracker order={order} onRestart={restart} />}
          </main>
          </div>
        </>
      )}
      <footer className="foot">
        {cfg.demo ? "Demo mode: sample applicants and simulated bank declines are enabled. " : ""}{cfg.payments?.provider === "razorpay" ? "Payments are processed by Razorpay." : "Payments are in test mode (no money moves); connect Razorpay for real payments."}
      </footer>
    </div>
  );
}
