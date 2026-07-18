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
        if (!cancelled) setBuild(health.cockpit_build);
      })
      .catch(() => {
        // Advisory banner: never surface an error for a health probe.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (build === null || build.status !== "stale") return null;
  const key = build.build_id ?? "unknown";
  if (dismissed || localStorage.getItem(STORAGE_KEY) === key) return null;

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
          localStorage.setItem(STORAGE_KEY, key);
          setDismissed(true);
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
