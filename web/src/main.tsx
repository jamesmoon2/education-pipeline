import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import AppErrorFallback from "./components/AppErrorFallback";
import ErrorBoundary from "./components/ErrorBoundary";
import { applyTheme, readThemePreference } from "./lib/theme";
import "./styles.css";

// Stamp the stored theme before the first render so an explicit choice
// never paints in the other scheme first.
applyTheme(readThemePreference());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* Last resort for a throw in the rail itself; routes have their own boundary in App. */}
    <ErrorBoundary fallback={(error) => <AppErrorFallback error={error} />}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
);
