import React from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/clerk-react";
import App from "./App.jsx";
import "./styles.css";

// Without a Clerk key the app runs in local dev mode (the API must also have auth switched off).
const key = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

createRoot(document.getElementById("root")).render(
  key ? (
    <ClerkProvider publishableKey={key} afterSignOutUrl="/">
      <App clerk />
    </ClerkProvider>
  ) : (
    <App />
  ),
);
