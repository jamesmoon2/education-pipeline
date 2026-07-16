import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getConfigProviders, getWorkspace } from "../api/client";
import type { ProviderAvailability, WorkspacePayload } from "../api/types";

export const WELCOME_DISMISSED_KEY = "ep.welcome.dismissed";

export function isWelcomeDismissed(): boolean {
  try {
    return localStorage.getItem(WELCOME_DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** Re-opens the welcome panel; wired to the Settings "Show welcome" control. */
export function resetWelcomeDismissal(): void {
  try {
    localStorage.removeItem(WELCOME_DISMISSED_KEY);
  } catch {
    // localStorage unavailable: the panel simply follows first_run.
  }
}

/**
 * First-run onboarding (spec §4.2): the three PRD §6.1 facts, detected
 * provider availability with manual mode first-class, and one primary CTA.
 * Shown only while the workspace has zero runs and the user has not
 * dismissed it; dismissal persists in localStorage. No multi-step tour.
 */
export default function WelcomePanel() {
  const [workspace, setWorkspace] = useState<WorkspacePayload | null>(null);
  const [providers, setProviders] = useState<ProviderAvailability[]>([]);
  const [dismissed, setDismissed] = useState(isWelcomeDismissed());

  useEffect(() => {
    let cancelled = false;
    getWorkspace().then(
      (payload) => {
        if (!cancelled) setWorkspace(payload);
      },
      () => {
        // Unknown workspace state: show nothing rather than a wrong welcome.
      },
    );
    getConfigProviders().then(
      (payload) => {
        if (!cancelled) setProviders(payload.providers);
      },
      () => {
        // Provider detection is progressive enhancement here.
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  if (dismissed || !workspace || !workspace.first_run) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(WELCOME_DISMISSED_KEY, "1");
    } catch {
      // Session-only dismissal when localStorage is unavailable.
    }
    setDismissed(true);
  };

  return (
    <section className="welcome-panel" aria-labelledby="welcome-heading">
      <h2 id="welcome-heading">Welcome to Education Pipeline</h2>
      <ul>
        <li>Everything is stored locally, in your workspace folder — nothing leaves this machine.</li>
        <li>
          Model work runs through a supported local provider, or through a manual copy/paste
          loop with any model you already use.
        </li>
        <li>
          Course quality improves when you give useful learner context and review the major
          gates yourself.
        </li>
      </ul>
      <h3>Model providers detected</h3>
      <ul>
        {providers.map((provider) => (
          <li key={provider.id}>
            {provider.label}:{" "}
            {provider.available ? "available" : provider.reason ?? "not available"}
          </li>
        ))}
        <li>Manual copy/paste — always available, no setup needed.</li>
      </ul>
      <p>
        <Link to="/new" className="primary-cta">
          Create your first course →
        </Link>
      </p>
      <p>
        <button onClick={dismiss}>Dismiss</button>
      </p>
    </section>
  );
}
