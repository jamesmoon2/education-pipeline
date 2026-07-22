import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CockpitBuild, HealthPayload } from "../api/types";

const STORAGE_KEY = "ep-cockpit-build-dismissed";

/**
 * Source-checkout freshness notice: shown when the daemon reports the
 * built cockpit is older than its source (spec: cockpit-build-freshness).
 * Advisory only — health failures and non-stale statuses render nothing.
 */
export default function BuildFreshnessBanner() {
  const [build, setBuild] = useState<CockpitBuild | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api<HealthPayload>("/v1/health")
      .then((health) => {
        if (!cancelled) setBuild(health.cockpit_build ?? null);
      })
      .catch(() => {
        // Advisory banner: never surface an error for a health probe.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The daemon injects a bootstrap notice into index.html so even a bundle
  // predating this component can warn. Avoid rendering a duplicate when that
  // server-owned notice is present.
  if (
    document.getElementById("ep-cockpit-build-banner") !== null ||
    build === null ||
    build.status !== "stale"
  ) {
    return null;
  }
  // build_id is always non-null once status is "stale" (the same stat()
  // that proves staleness yields it); the fallback is defensive only.
  const key = build.build_id ?? "unknown";
  let persistentlyDismissed = false;
  try {
    persistentlyDismissed = localStorage.getItem(STORAGE_KEY) === key;
  } catch {
    // Storage may be blocked; dismissal still works for this component mount.
  }
  if (dismissed || persistentlyDismissed) return null;

  return (
    <div className="build-banner" role="status">
      <p>
        This cockpit build is older than its source — you may be seeing old
        UI. Rebuild with <code>cd web &amp;&amp; npm run build</code> (or
        relaunch with <code>education-pipeline ui --rebuild</code>), then
        reload this page.
      </p>
      <button
        type="button"
        onClick={() => {
          try {
            localStorage.setItem(STORAGE_KEY, key);
          } catch {
            // Session-only dismissal is sufficient when storage is blocked.
          }
          setDismissed(true);
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
