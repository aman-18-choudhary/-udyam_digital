// Opens Razorpay Checkout for an order the server already created. The browser only collects the payment;
// the server confirms it (signature + amount check, and a signed webhook) before anything is marked paid.
let loading = null;

function loadScript() {
  if (window.Razorpay) return Promise.resolve();
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://checkout.razorpay.com/v1/checkout.js";
      s.onload = resolve;
      s.onerror = () => { loading = null; reject(new Error("Could not load the payment window. Check your connection and try again.")); };
      document.head.appendChild(s);
    });
  }
  return loading;
}

// Resolves with the three values Razorpay returns on success; rejects only when the customer closes the window.
// A failed attempt must NOT settle the promise: Razorpay keeps its window open for a retry, and a later
// success inside that same window still has to reach the server for verification.
export async function openCheckout(intent) {
  await loadScript();
  return new Promise((resolve, reject) => {
    let lastFailure = "";
    const rzp = new window.Razorpay({
      key: intent.key_id,
      order_id: intent.razorpay_order_id,
      amount: intent.amount_paise,
      currency: intent.currency,
      name: intent.name,
      description: intent.description,
      theme: { color: "#e4002b" },
      handler: (r) => resolve(r),
      modal: { ondismiss: () => reject(new Error(lastFailure || "Payment was cancelled. You can try again.")) },
    });
    rzp.on("payment.failed", (r) => { lastFailure = r?.error?.description || "The payment failed. You can try again."; });
    rzp.open();
  });
}
