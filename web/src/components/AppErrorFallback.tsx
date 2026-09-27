import { describeError } from "./ErrorBoundary";

interface AppErrorFallbackProps {
  error: unknown;
  /** Test seam; the app reloads the page. */
  onReload?: () => void;
}

/**
 * Last-resort fallback for the app-level boundary in main.tsx, shown when
 * the rail itself throws. It sits outside the router, so a full reload is
 * its only way out.
 */
export default function AppErrorFallback({
  error,
  onReload = () => window.location.reload(),
}: AppErrorFallbackProps) {
  return (
    <main className="app-error">
      <div className="error-fallback" role="alert">
        <h1>The cockpit stopped working</h1>
        <p>
          Your courses, profiles and runs are safe in the workspace. Reload the cockpit to
          carry on.
        </p>
        <details>
          <summary>Error details</summary>
          <pre>{describeError(error)}</pre>
        </details>
        <p className="error-fallback-actions">
          <button type="button" className="primary-button" onClick={onReload}>
            Reload the cockpit
          </button>
        </p>
      </div>
    </main>
  );
}
