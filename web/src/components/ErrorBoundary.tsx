import { Component } from "react";
import type { ReactNode } from "react";

interface ErrorBoundaryProps {
  /** A change clears a caught error (the route boundary passes the pathname). */
  resetKey?: unknown;
  /** Rendered in place of the children once they throw during render. */
  fallback: (error: unknown, reset: () => void) => ReactNode;
  children?: ReactNode;
}

interface ErrorBoundaryState {
  // A separate flag, since anything (even undefined) can be thrown.
  hasError: boolean;
  error: unknown;
  resetKey: unknown;
}

/**
 * One boundary, two placements (Phase 6 decision 1): around <Routes> so a
 * page's render error leaves the rail usable, and around <App/> as a last
 * resort. Render errors only: event-handler and async errors never reach a
 * React boundary (ErrorNotice covers API failures).
 */
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  // Clearing here rather than in componentDidUpdate means children that
  // throw again under the new key are caught once, not rendered twice.
  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: ErrorBoundaryState,
  ): Partial<ErrorBoundaryState> | null {
    if (Object.is(props.resetKey, state.resetKey)) return null;
    return { hasError: false, error: null, resetKey: props.resetKey };
  }

  reset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) return this.props.fallback(this.state.error, this.reset);
    return this.props.children;
  }
}

/** A thrown value as display text; never throws itself. */
export function describeError(error: unknown): string {
  if (error instanceof Error) return error.message ? `${error.name}: ${error.message}` : error.name;
  try {
    return String(error);
  } catch {
    return "An unknown error was thrown.";
  }
}
