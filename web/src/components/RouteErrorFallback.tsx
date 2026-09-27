import { Link } from "react-router-dom";
import { describeError } from "./ErrorBoundary";

interface RouteErrorFallbackProps {
  error: unknown;
  /** Clears the route boundary and renders the page again. */
  onRetry: () => void;
}

/**
 * Stands in for a page that threw while rendering. The rail stays outside
 * the route boundary, so the rest of the cockpit keeps working.
 */
export default function RouteErrorFallback({ error, onRetry }: RouteErrorFallbackProps) {
  return (
    <section className="error-fallback" role="alert">
      <h2>This page stopped working</h2>
      <p>
        The rest of the cockpit still works. Try the page again, or go back to the library.
      </p>
      <details>
        <summary>Error details</summary>
        <pre>{describeError(error)}</pre>
      </details>
      <p className="error-fallback-actions">
        <button type="button" onClick={onRetry}>
          Try again
        </button>
        <Link to="/">Back to the library</Link>
      </p>
    </section>
  );
}
