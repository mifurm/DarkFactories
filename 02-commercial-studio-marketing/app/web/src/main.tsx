import "@fontsource-variable/inter";
import "@fontsource-variable/fraunces";
import "./index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ApiError } from "./api";
import { initLang } from "./i18n";

initLang(); // ?lang= → saved choice → browser languages → en; sets <html lang> before the first paint

// Failed API calls are already shown to the user as a (localized) toast: do not let the rejected promise of an event handler surface as an unhandled page error.
window.addEventListener("unhandledrejection", (e) => {
  if (e.reason instanceof ApiError) e.preventDefault();
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
