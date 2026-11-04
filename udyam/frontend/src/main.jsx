import React from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/clerk-react";
import { dark } from "@clerk/themes";
import App from "./App.jsx";
import "./styles.css";

// Without a Clerk key the app runs in local dev mode (the API must also have auth switched off).
const key = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

// Clerk's sign-in and account widgets follow the app's dark glass look.
const appearance = {
  baseTheme: dark,
  variables: { colorPrimary: "#ff1f45", colorBackground: "#15101d", colorInputBackground: "rgba(255,255,255,0.06)", borderRadius: "0.9rem", fontFamily: "inherit" },
  elements: { card: { boxShadow: "0 30px 80px -30px rgba(255,31,69,0.45), 0 0 0 1px rgba(255,255,255,0.12) inset", backdropFilter: "blur(18px)", background: "rgba(21,16,29,0.78)" } },
};

createRoot(document.getElementById("root")).render(
  key ? (
    <ClerkProvider publishableKey={key} afterSignOutUrl="/" appearance={appearance}>
      <App clerk />
    </ClerkProvider>
  ) : (
    <App />
  ),
);
