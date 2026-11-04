// Clerk supplies the session token. App.jsx registers the getter once the user is signed in.
let getToken = async () => null;
export const setTokenGetter = (fn) => { getToken = fn; };

async function authHeaders(extra = {}) {
  const t = await getToken();
  return t ? { ...extra, authorization: `Bearer ${t}` } : extra;
}

async function req(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const res = await fetch(`/api${path}`, {
    ...opts,
    headers: await authHeaders(opts.body && !isForm ? { "content-type": "application/json" } : {}),
    body: opts.body && !isForm ? JSON.stringify(opts.body) : opts.body,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d : d?.problems?.[0]?.message || `Request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

// Server-sent events over fetch(), because EventSource cannot send an Authorization header.
export function streamOrder(id, onOrder, onState) {
  const ctrl = new AbortController();
  let lastId = "0";
  (async () => {
    while (!ctrl.signal.aborted) {
      try {
        const res = await fetch(`/api/orders/${id}/stream`, {
          headers: await authHeaders({ "last-event-id": lastId, accept: "text/event-stream" }),
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(String(res.status));
        onState(true);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const frame = buf.slice(0, i);
            buf = buf.slice(i + 2);
            const idLine = frame.match(/^id: (.*)$/m);
            const dataLine = frame.match(/^data: (.*)$/m);
            if (idLine) lastId = idLine[1];
            if (dataLine && /^event: order$/m.test(frame)) onOrder(JSON.parse(dataLine[1]));
          }
        }
        if (/ACTIVATED/.test(lastId)) return;
      } catch {
        if (ctrl.signal.aborted) return;
      }
      onState(false);
      await new Promise((r) => setTimeout(r, 2000));
    }
  })();
  return () => ctrl.abort();
}

export const api = {
  config: () => req("/config"),
  me: () => req("/me"),
  start: (language) => req("/advisor/start", { method: "POST", body: { language } }),
  message: (session_id, text) => req("/advisor/message", { method: "POST", body: { session_id, text } }),
  catalogue: (session_id) => req(`/catalogue?session_id=${session_id}`),
  quote: (body) => req("/quote", { method: "POST", body }),
  notice: () => req("/consent/notice"),
  consent: (session_id, notice_version) =>
    req("/consent", { method: "POST", body: { session_id, accept: true, notice_version } }),
  withdraw: (session_id) => req(`/consent/${session_id}`, { method: "DELETE" }),
  lookup: (body) => req("/kyc/lookup", { method: "POST", body }),
  openCase: (session_id, gstin) => req("/kyc/cases", { method: "POST", body: { session_id, gstin } }),
  upload: (caseId, file, doc_type) => {
    const f = new FormData();
    f.append("file", file);
    f.append("doc_type", doc_type);
    return req(`/kyc/cases/${caseId}/documents`, { method: "POST", body: f });
  },
  specimens: () => req("/kyc/specimens"),
  specimen: (caseId, applicant) => req(`/kyc/cases/${caseId}/specimen`, { method: "POST", body: { applicant } }),
  verify: (caseId) => req(`/kyc/cases/${caseId}/verify`, { method: "POST" }),
  order: (body) => req("/orders", { method: "POST", body }),
  pay: (id, body) => req(`/orders/${id}/pay`, { method: "POST", body }),
  paymentIntent: (id) => req(`/orders/${id}/payment-intent`, { method: "POST" }),
  verifyPayment: (id, body) => req(`/orders/${id}/verify-payment`, { method: "POST", body }),
  getOrder: (id) => req(`/orders/${id}`),
  myOrders: () => req("/my/orders"),
  boFunnel: () => req("/backoffice/funnel"),
  boLeads: (q) => req(`/backoffice/leads?${new URLSearchParams(q)}`),
  boModel: () => req("/backoffice/model"),
  boHandoffs: () => req("/backoffice/handoffs"),
  boOrders: () => req("/backoffice/orders"),
  reviews: () => req("/ops/reviews"),
  reviewDecision: (id, approve, note = "") => req(`/ops/reviews/${id}/decision`, { method: "POST", body: { approve, note } }),
  reviewDocUrl: async (id, type) => {
    const res = await fetch(`/api/ops/reviews/${id}/documents/${type}`, { headers: await authHeaders() });
    if (!res.ok) throw new Error(`Could not load the document (${res.status})`);
    return URL.createObjectURL(await res.blob());
  },
  advanceOrder: (id) => req(`/ops/orders/${id}/advance`, { method: "POST" }),
};

export const inr = (n) => "₹" + Math.round(n ?? 0).toLocaleString("en-IN");
